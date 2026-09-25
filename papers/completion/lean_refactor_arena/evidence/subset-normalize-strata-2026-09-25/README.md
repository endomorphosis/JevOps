# Strata constructive normalization — 2026-09-25

## Fixed hypothesis and baseline

The [preceding reconstruction experiment](../subset-triple-strata-2026-09-25/README.md)
left explicit `True` connectives in its restricted-simp draft. Its grind-based
drafts closed the proof but added `Classical.choice` and used more heartbeats.
This follow-up uses the same **169-token incumbent**, not the older 185-token
solver baseline. Historical sources are hints/inputs, never reused verification
events. Fresh original/incumbent controls are required in every phase.

The existing three-leaf matcher replaces only the `ite` branch's append subtree,
leaving `cases Hnorm`, the theorem statement and every other branch unchanged.
The new opt-in `subset-triple-normalize` profile has exactly two predetermined
scripts; the only difference is `forall_and`:

```lean
simp_all only [List.Subset, List.mem_append, or_imp, forall_and,
  true_implies, true_or, or_true, implies_true, and_self]

simp_all only [List.Subset, List.mem_append, or_imp,
  true_implies, true_or, or_true, implies_true, and_self]
```

Generated source uses one line per tactic. Full proof lengths are **163** and
**161** tokens, compared with 169 for the incumbent and 222 for the original.
The normalization lemmas were inspected in the pinned Lean 4.26.0
`Init/SimpLemmas.lean`; syntactic use of them does not itself certify validity,
no axiom growth, or lower cost. Whole-source checking remains mandatory.

## Frozen protocol and execution boundary

Task: `CallElimCorrect.extractedOldExprInVars`; Strata commit
`451e5f047bafa010d178856db76c00029bfa4d7f`; sole declared pin `v4.26.0`.
The source comes from [the previously confirmed 169-token draft](../subset-triple-strata-2026-09-25/incumbent.json).

- Two candidates, no adaptive generation or retries.
- Screening: original/incumbent/two drafts × two branch orders × two repeats
  = **16 fresh native checks**.
- Reserve **18** additional checks for original/incumbent/fixed winner × two
  orders × three fresh confirmation repeats. No alternate winner after failure.
- **34-check ceiling**, frozen before execution; seeds 17/18, `strict-dual-v1`,
  100-raw-heartbeat noise floor. Both costs must improve against original and
  incumbent in every stratum; target/type preservation and no axiom growth apply.
- No model/API calls, training, provisioning, builds or promotion. No unused
  confirmation allowance is reassigned to discovery.

The existing `arena_leaf_pilot`, `NativeLeanVerifier` and strict selector execute
the experiment from a read-only source snapshot. The preparation `flock`
serializes native work on the existing 50 GB capped volume. Capture requires
200 MB free; subsequent resource checks preserve a 100 MB reserve. Dependencies
and the checker are trusted local infrastructure. This is **not an OS sandbox**,
adversarial-code safety guarantee, held-out evaluation, or official Arena score.

## Native result: no improvement

The run completed successfully with **16/16 native checks VERIFIED** and
selector status **NO_IMPROVEMENT**, in **381.62 seconds** wall time including
source/resource checks. All four arms were admissible: their recorded axiom
sets were exactly `propext` and `Quot.sound`. Unlike the previous grind drafts,
these two normalized proofs did not introduce `Classical.choice`.

| Arm | Proof tokens | Reference-first raw heartbeats | Candidate-first raw heartbeats |
| --- | ---: | ---: | ---: |
| Original | 222 | 2,607,572–2,607,574 | 2,607,585–2,607,587 |
| Incumbent | 169 | 1,283,749–1,283,749 | 1,283,762–1,283,762 |
| Normalized (`composition-0`) | 163 | 1,674,338–1,674,340 | 1,674,351–1,674,352 |
| Compact normalized (`composition-1`) | 161 | 1,653,905–1,653,905 | 1,653,918–1,653,918 |

The drafts save **3.55% / 4.73%** of incumbent tokens but use **30.43% /
28.83% more** raw heartbeats, comparing means over the same four samples per
arm. Both improve on the original, but neither beats the actual incumbent in
both costs. This is a measured cost regression, not a proof failure or an
inconclusive noise overlap. No statistical significance claim is made.

The 169-token incumbent is retained and freshly verified. **No confirmation
checks** were launched and the unused 18-check reserve was not reassigned.
No retries, production promotion, model/API calls, downloads, dependency builds,
or training occurred. `official_score` remains null and worker metric parity is
unconfirmed. This strict-dual batch did not run aggregate-objective selection.

The source binding reports **UNCHANGED** before and after native work. The
[report consistency audit](audit/summary.md) returns **CONSISTENT**, accounting
for 16/16 samples and both branch orders. That audit reads historical JSON;
it performs zero new Lean checks and is not an independent proof attestation.

Artifacts: [native report](report.json), [summary](summary.md),
[accounting](accounting.json), [source binding](source-binding.json),
[screen reservation](screen-reservation.json), [leaf plan](plan.json),
[selection protocol](selection-protocol.json), [launch](launch.json), and
[source manifest](source-manifest.json).

Reproduce the record-consistency audit (not the native verification):

```bash
PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
python -m jevops.arena_report_audit \
  --protocol papers/completion/lean_refactor_arena/evidence/subset-normalize-strata-2026-09-25/selection-protocol.json \
  --report papers/completion/lean_refactor_arena/evidence/subset-normalize-strata-2026-09-25/report.json \
  --output-dir papers/completion/lean_refactor_arena/evidence/subset-normalize-strata-2026-09-25/audit
```

Next hypothesis, **not evaluated here**: retain the constructive append-lemma
structure and nominate a direct proof-term replay with bounded elaboration,
instead of repeatedly normalizing the entire branch context. This result does
not establish global minimality or justify dropping the no-axiom-growth gate.

## Commands and source identity

Plan only (zero native/model calls):

```bash
PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
python -m jevops.arena_leaf_pilot \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent papers/completion/lean_refactor_arena/evidence/subset-triple-strata-2026-09-25/incumbent.json \
  --profile subset-triple-normalize
```

It emitted token counts 163/161, required processes 34, plan SHA-256
`5d7aaf432ae2778641961cc585ee35d1adff35fbc46be9a3b23d45878b50ea47`.

Runtime root: `/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/subset-normalize-strata-pmvcna5d`.
Snapshot: 2,004 files, 52,023,384 bytes; manifest SHA-256
`40bd0afb4dae6a9d9365b90746f995fa6a735a803fe946efc13dbb05ea7a3d3e`.
Content hashes establish identity, not independent proof authority.

Capture used `arena_snapshot.create_snapshot` under the preparation lock, with
`jevops`, `tests`, `papers/completion/lean_refactor_arena`, `pyproject.toml`,
`pytest.ini`, `conftest.py`, `ARENA_COMPOSITIONS.md`, and explicit inputs for the
169-token incumbent and `work/projects-prepared-20.json`. The execution CLI
reacquires the lock and validates the snapshot and dependencies before work.

Actual command, cwd at the runtime root's `source`. Only PATH/HOME/LANG/LC_ALL
were forwarded, with `PYTHONDONTWRITEBYTECODE=1`, `JEVOPS_REGISTER_LRA_HOOKS=0`,
`JEVOPS_USE_EXTERNAL_DEPS=0`, `JEVOPS_USE_EXTERNAL_ROUTER=0`, and TMPDIR set to
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp`:

```bash
/home/barberb/.local/bin/python -I -B -c \
  'import sys; sys.path.insert(0,sys.argv.pop(1)); from jevops.arena_leaf_pilot import main; raise SystemExit(main())' \
  /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/subset-normalize-strata-pmvcna5d/source \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent inputs/incumbent.json --profile subset-triple-normalize \
  --execute --max-processes 34 \
  --snapshot-manifest-sha256 40bd0afb4dae6a9d9365b90746f995fa6a735a803fe946efc13dbb05ea7a3d3e \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --projects inputs/projects.json \
  --elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
  --output /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/subset-normalize-strata-pmvcna5d/selection
```

A rerun must use a newly captured source and new output directory; it cannot
overwrite this run or claim these historical receipts as new proof/cost events.

## Fresh regression tests

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-normalize-tests-COZB1X14/cache \
  --junitxml=/tmp/jevops-normalize-tests-COZB1X14/regression.xml \
  tests/test_arena_compositions.py tests/test_arena_leaf_pilot.py tests/test_arena_pareto.py -q
```

Observed: **463 passed, 3 skipped**, zero reused, **427 fresh passes sealed**,
32.45 seconds. Fourteen added cases cover exact normalized replacements,
the isolated `forall_and` factor, unchanged proof regions, the full confirmation
reserve and the distinction between a native `VERIFIED` receipt and admissible
no-axiom-growth refactoring. Unsupported-input tests also exercise both new
strategies. No native proof or performance evidence is inferred from fixtures.

The supplemental rules/provider/audit suite also ran fresh on a byte-identical
read-only host-filesystem copy of the snapshot:

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
python -I -B -c \
  'import os,sys; os.chdir(sys.argv[1]); sys.path.insert(0,sys.argv.pop(1)); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' \
  /tmp/jevops-normalize-safety-1t9o4Jm6/source --test-seal=refresh \
  -o cache_dir=/tmp/jevops-normalize-safety-1t9o4Jm6/cache \
  --junitxml=/tmp/jevops-normalize-safety-1t9o4Jm6/safety.xml \
  tests/test_arena_rules.py tests/test_arena_providers.py tests/test_arena_report_audit.py -q
```

Observed: **139 passed, 3 skipped**, zero reused, **133 fresh passes sealed**,
9.77 seconds. Combined completed suites: **602 passed, 6 skipped**, with **560
fresh passes sealed**. [Targeted JUnit](regression.xml), [supplemental JUnit](safety.xml).
Skips are not passes; no full-repository test result is claimed. The copied
snapshot verified `UNCHANGED` afterward, and the four edited implementation/test
files still matched the captured bytes in the workspace.

## Files changed and trust boundary

- `jevops/arena_compositions.py`: two explicit normalized simp scripts/rule
  names; existing exact-layout matcher, scope/source limits and draft boundary
  reused, not a new proof engine or verifier.
- `jevops/arena_leaf_pilot.py`: one new fixed two-arm opt-in profile; previous
  profiles, confirmation requirements and selector defaults unchanged.
- `tests/test_arena_compositions.py`, `tests/test_arena_leaf_pilot.py`: fourteen
  additional cases plus both strategies in existing malformed-layout checks.
- `ARENA_COMPOSITIONS.md`, root README, safety plan and this archive: commands,
  implemented scope, measured outcomes and limits.

Python tests enforce nomination shape/bounds and full resource reservation;
they do not prove semantic correctness of a replacement. Native checker and
selector checks enforce target/type preservation, allowed axioms, no axiom
growth over reference, fresh-context applicability and the cost criterion.
No content hash, saved report, or tactic's mere success substitutes for these
checks. Generic reconstruction, trained policies, held-out generalization,
automatic promotion and stronger adversarial execution/metric defenses are
not implemented by this slice.
