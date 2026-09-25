# Strata three-leaf reconstruction — 2026-09-25

## Result: smaller proofs, but no admissible improvement

**20 native checks completed**; the selector returned `NO_IMPROVEMENT` and did
not use its 18-check confirmation reserve. The 169-token incumbent was freshly
verified in all four screening strata/repetitions and remains unchanged.

| Arm | Tokens | Raw heartbeat range across screening samples | Admission result |
| --- | ---: | ---: | --- |
| Original | 222 | 2,607,572–2,607,595 | Valid control |
| Incumbent | 169 | 1,283,749–1,283,762 | Valid retained baseline |
| Simplification only | 153 | No valid cost samples | Four Lean rejections: unsolved goals |
| Grind only | 149 | 1,644,393–1,644,515 | Four native `VERIFIED` outcomes, but added `Classical.choice`; also slower |
| Simplification then grind | 153 | 1,821,192–1,821,249 | Four native `VERIFIED` outcomes, but added `Classical.choice`; also slower |

The 149-token draft removes 20 tokens (11.83%) but averages **28.10% more raw
heartbeats** than the incumbent. The 153-token grind composition removes 16
tokens (9.47%) but averages **41.87% more raw heartbeats**. These are descriptive
means of the four matched screening samples, not fresh confirmation,
statistical/generalization claims, or an official score. Both would fail the
strict cost criterion even without the axiom-policy rejection.

`VERIFIED` in the native progress log means the checker established a closed,
type-preserving proof within its standard allowed axiom set. It does **not**
mean eligibility as a refactor: the selector additionally rejects axiom growth
relative to the original, whose axioms are only `propext` and `Quot.sound`.
The eight grind-based samples added `Classical.choice`; the report records
`axiom_expansion_over_reference`. All four simplification-only samples instead
failed with `candidate_errors`. No timeout or infrastructure failure occurred.

The simplification-only diagnostics retain `True → ...` premises and goals
containing `True ∨ ...` / `... ∨ True`. Its restricted whitelist exposed the
membership problem but omitted the usual propositional normalization lemmas.
A focused next hypothesis is to add a bounded set such as `true_implies`,
`true_or`, `or_true`, `implies_true`, and `and_self`, available in the pinned
`Init/SimpLemmas.lean`, and recheck both cost and axioms. **That new variant was
not generated or run in this fixed experiment.** No post-result batch expansion
occurred; this pass establishes neither global minimality nor an impossibility
of constructive reconstruction.

Artifacts: [fixed pilot plan](plan.json), [selector protocol](selection-protocol.json),
[report with all samples and diagnostics](report.json), [summary](summary.md),
[resource accounting](accounting.json), [source binding](source-binding.json),
[source manifest](source-manifest.json), [launch metadata](launch.json).
The source snapshot stayed `UNCHANGED`; the launched command returned 0 after
468.93 seconds. No recommendation or candidate promotion was emitted. Actual
API cost was not measured; no model/API was called.

Independent **record-consistency** audit returned `CONSISTENT`:
[audit report](audit/audit.json), [audit summary](audit/summary.md). It performed
zero new native checks and is not a cryptographic attestation or a new proof.

```bash
PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
python -m jevops.arena_report_audit \
  --protocol papers/completion/lean_refactor_arena/evidence/subset-triple-strata-2026-09-25/selection-protocol.json \
  --report papers/completion/lean_refactor_arena/evidence/subset-triple-strata-2026-09-25/report.json \
  --output-dir papers/completion/lean_refactor_arena/evidence/subset-triple-strata-2026-09-25/audit
```

## Baseline correction

The preceding support-deletion pass fixed a 185-token comparator but overlooked
the [archived 169-token strict winner](../native-subset-shared-target-2026-09-24/summary.md).
That archive's selector report is internally `CONSISTENT`, with all 18 fresh
confirmation samples verified at the time. The saved winning source is 169
tokens and had 1,283,749–1,283,764 raw heartbeats, versus the earlier 175-token
incumbent. These are **historical** observations, not new checks this turn.
The 161-token alternative in the subsequent pair-simplification experiment
was slower and was not confirmed as a strict winner.

The older 185-token and 190-token sources remain valid historical branch
baselines. The no-candidate support-deletion result is unchanged, but 185 must
not be described as the strongest known strict incumbent. This experiment
explicitly uses the 169-token source as its incumbent, with fresh original and
incumbent controls in every phase. It does not borrow archived receipts or
claim fresh comparisons against the 185-token source.

## Implemented intervention and frozen protocol

The existing `arena_compositions` matcher now recognizes one exact three-leaf
right-nested append subtree and nominates three reconstructions. It preserves
the original theorem, `cases Hnorm` setup, and all other branches. The fixed
`arena_leaf_pilot` profile is `subset-triple-reconstruct`:

| Arm | Replacement of that subtree | Proof tokens |
| --- | --- | ---: |
| `composition-0` | `simp_all only [List.Subset, List.mem_append, or_imp, forall_and]` | 153 |
| `composition-1` | `grind only [List.Subset, List.mem_append]` | 149 |
| `composition-2` | `simp_all only [List.Subset, List.mem_append]` then `grind only []` | 153 |

These are deterministic source proposals, not learned tactics or a semantic
equivalence certificate. The whole-source native checker must establish every
draft's validity, target preservation, and axiom policy. The original corpus
proof is 222 tokens; the declared task is
`CallElimCorrect.extractedOldExprInVars`, Strata commit
`451e5f047bafa010d178856db76c00029bfa4d7f`, sole pin `v4.26.0`.

The predeclared ceiling is **38 native checks**: five arms (original, incumbent,
three candidates) × two branch orders × two screening repeats = 20, then
original/incumbent/fixed winner × two orders × three fresh confirmation repeats
= 18. `strict-dual-v1` requires fewer tokens and separated lower raw heartbeats
against both comparators in every stratum, with a 100-raw-unit noise floor.
Seeds are 17/18; no retries, alternative confirmation winners, post-result batch
expansion, model calls, training, downloads, dependency builds, or promotion.

The runtime uses the existing native verifier, leaf pilot, and selector. Source
capture is immutable; the existing preparation lock serializes execution on the
50 GB capped volume. This is trusted-local execution, not an OS sandbox,
arbitrary-code safety guarantee, distributed search, or official Arena score.
This is one exposed public task, not held-out or corpus-wide performance.

## Reproduction

Plan only; no Lean, model, or network calls:

```bash
PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
python -m jevops.arena_leaf_pilot \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent papers/completion/lean_refactor_arena/evidence/subset-triple-strata-2026-09-25/incumbent.json \
  --profile subset-triple-reconstruct
```

The observed plan requested 38 processes and emitted token counts 153/149/153.
Runtime root: `/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/subset-triple-strata-3y3glr31`.
Source capture: 1,990 files, 51,387,798 bytes; manifest SHA-256
`e741101b1da24ea0b03b06ac758014770087f06c9fbd91f1c2203438afc30f90`.
Hashes identify content, not independent proof authority.

The capture used `arena_snapshot.create_snapshot` under `arena_prepare.exclusive`,
including `jevops`, `tests`, `papers/completion/lean_refactor_arena`,
`pyproject.toml`, `pytest.ini`, `conftest.py`, `ARENA_COMPOSITIONS.md`;
`inputs/incumbent.json` is the four-field source in this directory and
`inputs/projects.json` is the prepared `work/projects-prepared-20.json` mapping.
It required 200 MB free before capture. The native CLI reacquires the same lock,
verifies the snapshot and dependency context, and checks a 100 MB free reserve.

Actual native command, with cwd at that root's `source` and only PATH/HOME/
LANG/LC_ALL forwarded, external hooks/router disabled and TMPDIR set to
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp`:

```bash
/home/barberb/.local/bin/python -I -B -c \
  'import sys; sys.path.insert(0,sys.argv.pop(1)); from jevops.arena_leaf_pilot import main; raise SystemExit(main())' \
  /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/subset-triple-strata-3y3glr31/source \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent inputs/incumbent.json --profile subset-triple-reconstruct \
  --execute --max-processes 38 \
  --snapshot-manifest-sha256 e741101b1da24ea0b03b06ac758014770087f06c9fbd91f1c2203438afc30f90 \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --projects inputs/projects.json \
  --elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
  --output /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/subset-triple-strata-3y3glr31/selection
```

Use a newly captured, owned directory for a rerun, not the existing output.
Neither current code edits nor archived metadata confer admission in a new epoch.

## Tests executed before native launch

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-triple-tests-FnNkfOg0/cache \
  --junitxml=/tmp/jevops-triple-tests-FnNkfOg0/regression.xml \
  tests/test_arena_compositions.py tests/test_arena_leaf_pilot.py tests/test_arena_pareto.py -q
```

Observed: **449 passed, 3 skipped**, zero reused, **415 fresh passes sealed**,
31.47 seconds. Thirty-five new cases cover exact layouts, bullets, discharge
syntax, terminal boundaries, unsupported inputs, the 169-token baseline,
source/candidate schemas, zero caps, deduplication and full confirmation reserve.
Native tests were explicitly disabled; fixtures do not establish Lean validity.

Supplemental rules/provider/audit regression: **139 passed, 3 skipped**, zero
reused, **133 fresh passes sealed**, 9.54 seconds. The command used a read-only
host-filesystem copy of the exact same snapshot (verified `UNCHANGED` afterward):

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
python -I -B -c \
  'import os,sys; os.chdir(sys.argv[1]); sys.path.insert(0,sys.argv.pop(1)); import pytest; raise SystemExit(pytest.main(sys.argv[1:]))' \
  /tmp/jevops-triple-safety-K0skoKAz/source --test-seal=refresh \
  -o cache_dir=/tmp/jevops-triple-safety-K0skoKAz/cache \
  --junitxml=/tmp/jevops-triple-safety-K0skoKAz/safety.xml \
  tests/test_arena_rules.py tests/test_arena_providers.py tests/test_arena_report_audit.py -q
```

JUnit artifacts: [targeted regression](regression.xml), [supplemental](safety.xml).
Combined: 588 passes, 6 skips, 548 fresh passes sealed. Skips are not counted as
successes. No full-repository pass, native proof result, or model evaluation
is inferred from the offline suites.

## Files and boundaries

- `jevops/arena_compositions.py`: bounded three-leaf recognition, three fixed
  reconstruction scripts, integration in the existing rule allowlist/manifest.
- `jevops/arena_leaf_pilot.py`: opt-in fixed three-arm profile; existing full
  budget reservation, snapshot checks and strict selector reused unchanged.
- `tests/test_arena_compositions.py`, `tests/test_arena_leaf_pilot.py`: 35 new
  offline cases, including refusal to run with only the screening allowance.
- `ARENA_COMPOSITIONS.md`, `LEAN_TOKEN_HEARTBEAT_SAFETY_PLAN.md`, README and
  evidence notes: implemented scope, baseline correction, commands and results.

The closed tactic vocabulary and syntactic bounds are enforced/tested in
Python. Source edits are **not** claimed semantics-preserving by that matcher:
Lean checking remains required. Target/context/type/axiom and resource checks
are provided by the existing verifier/selector, not new policy-supplied flags.
The prepared environment, native checker and local filesystem remain trusted.
General reconstruction, trained policy, held-out gains, automatic promotion,
and stronger execution/metric-authenticity defenses remain outside this slice.
