# Aggregate nomination: matched Strata pilot

Task: `CallElimCorrect.extractedOldExprInVars`, Strata commit
`451e5f047bafa010d178856db76c00029bfa4d7f`, Lean `v4.26.0`, its sole declared
pin. This is an exposed public-warmup task, not a blind holdout or submission.

## Observed result: no new nominee

The [run](report.json) ended **`NO_CANDIDATE`**, reason
`bounded_discovery_no_eligible_draft`. Both arms used their eight calls and
reached the same checked source frontier. Neither emitted a nominee, so
**screening and confirmation were not run**. The 185-token incumbent was
retained; there is no new score gain or official score to report.

| Arm | Calls | Seed → alternative tokens | Seed → alternative raw heartbeats | Nominees |
| --- | ---: | ---: | ---: | ---: |
| `dual-first` | 8 | 185 → 197 | 2324400 → 2274909 | 0 |
| `aggregate` | 8 | 185 → 197 | 2324397 → 2274903 | 0 |

The alternative is **6.4865% larger** for **2.1292–2.1293% fewer heartbeats**,
so its seed-normalized aggregate nomination gain is negative. Unlike the
previous Physlib specialization, this longer proof does not earn enough
heartbeat savings to justify its size increase. This is a single-sample
discovery comparison, not freshly confirmed comparative performance or proof
that the incumbent is optimal. The small raw-count differences between arms
remain in the reports; costs are not fabricated as identical.

The successful local edit replaced line 31's `simp_all` with:

```lean
simp_all only [forall_const, imp_false, implies_true, List.mem_append, true_or]
```

Both original and incumbent controls freshly verified before discovery, with
2607572 and 2324399 raw heartbeats respectively and the same observed axioms
(`propext`, `Quot.sound`). Those pre-existing gains are not new optimizer wins.
The controls plus sixteen discovery attempts used **18 native checks**,
18 phase reservations, within the frozen ceiling of 52. Twelve checks verified
(including probes); six candidate attempts were rejected. Rejection is not
disproof of the theorem. The remaining 34-check capacity was not spent.

Native orchestration took **415.03 seconds**. The launcher took 651.19 seconds
including 23 ten-second sleeps waiting for the preparation lock and setup.
The source was unchanged before and after; see [source-binding.json](source-binding.json)
and [launch-result.json](launch-result.json). Free storage afterward was
869883904 bytes within the validated 50 GB volume. The process exited and
released its lock; no persistent optimization loop was started.

The [diagnostic summary](diagnostic-summary.json) checks plan identity,
resource accounting, work/outcome equality and absence of selection. Its
`CONSISTENT` status is only historical bookkeeping, with `proof_verified: false`
and zero fresh native processes. It neither authenticates the receipts nor
establishes additional proofs. The two discovery reports retain the full
[dual-first](discovery-dual-first.json) and [aggregate](discovery-aggregate.json)
attempt histories.

### Next concrete bottleneck

Two of each arm's eight calls replayed suggestions against only line 8 of a
multiline `simp`. The edit preserved the old continuation on line 9, producing
`unexpected identifier; expected command` and unsolved goals. These candidates
were correctly rejected and never became frontier nodes. A further attempt
to remove all support from the valid 197-token proof also failed; validity of
the parent does not authorize that child.

Both arms recorded omitted query sites under the two-site limit. The next
separately frozen intervention should bind suggestions to complete tactic
source spans (and preserve the surrounding `<;>`/`at *` behavior), with offline
multiline/delimiter tests and whole-source native replay. Multiple `simp?`
messages at one induction site may apply to different goals; blindly replacing
the whole command with one per-goal hint is not justified either. This span/
goal-scoping repair is **diagnosed, not implemented in this pass**. The completed
trial was not extended after inspecting its results.

## Frozen question and controls

Does changing only final draft nomination improve the result of the same
bounded solver search beyond a known incumbent? The seed is the saved
185-token proof from the full-set development benchmark, not the 222-token
original. Its historical label `historical-260` uses an obsolete counter;
the current reference-compatible tokenizer counts 185. That label and old
receipts are not verification authority. Both original and incumbent receive
fresh native controls, and any final recommendation must improve on both.

The new `aggregate-nomination-v1` pilot profile uses two separately executed
arms, in predeclared order:

| Arm | Search | Final nomination |
| --- | --- | --- |
| `dual-first` | `balanced-frontier-v1` | `discovery-dual-first-v1` |
| `aggregate` | `balanced-frontier-v1` | `discovery-aggregate-v1` |

Both get eight calls, four states, depth two, two sites and one draft, with
the same byte/proposal limits. There is no cross-arm receipt reuse or borrowing
of unused budget. This compares nomination only, not a different exploration
algorithm; identical checked frontiers are a possible and informative outcome.
The aggregate nomination heuristic uses seed-normalized discovery costs;
with a non-original seed these weights can differ from final reference-normalized
selection. No optimal-ranking guarantee is claimed.

The exact-source union of nominees enters the same `aggregate-local-v1`
selector: two screening repetitions and three fresh confirmation repetitions
per branch order, seed 17/18, 100 raw-unit floor. Only the union-selected winner
is confirmed. Losing nominees have screening observations, not independently
confirmed score claims. All proof/type/axiom/context gates remain unchanged.

The full **52-check ceiling** reserves two controls, sixteen discovery calls,
sixteen possible screening calls and eighteen possible confirmation calls.
Duplicate nominees or no eligible nominees reduce actual work; unused capacity
is not reallocated. A failed control stops discovery, and infrastructure failure
in either arm cannot be dropped to claim a successful comparison.

No source promotion, training, model calls, downloads or builds are enabled.
Execution uses the exclusive preparation lock and existing 50 GB capped volume.
It is single-process orchestration of serial checks, not an OS sandbox.

## Reproduction

Runtime parent:
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/solver-nomination-20260924-U2wRR9`.
Its `source` snapshot contains 1541 files / 46514842 bytes; externally retained
manifest SHA-256:
`9b2c85bf440c7b642e7373e61fca02b4c2dabfe0147488437fc484b14bdfe73c`.
Copied inputs include exact project mappings and the historical incumbent.
Hashes identify content, not proof truth or loaded Python bytecode.

The launcher uses `python -I -B`, explicitly imports JevOps from this snapshot,
disables external hooks/router dependencies, sets TMPDIR inside the capped
volume and validates the snapshot. It waits at most 600 seconds for a busy
preparation lock, without launching Lean or retrying an already started run.
The pilot itself acquires the lock, checks volume/output/input containment,
requires at least 100 MB free, and validates source identity before and after.
Actual argv and launch observations are retained as JSON.

From that frozen source root, the effective pilot command is:

```bash
python -m jevops.arena_solver_pilot \
  --comparison aggregate-nomination-v1 \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent inputs/incumbent.json \
  --execute --max-processes 52 \
  --snapshot-manifest-sha256 9b2c85bf440c7b642e7373e61fca02b4c2dabfe0147488437fc484b14bdfe73c \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --projects inputs/projects.json \
  --elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
  --output /prepared/new-nomination-run
```

Without `--execute`, the CLI only emits the frozen plan. Use a new output path
inside the validated volume; missing dependencies do not trigger provisioning.

## Offline tests

The frozen targeted regression passed **593 tests, 5 skipped, 89 deselected**
in 11.54 seconds. No native integration or API calls were enabled. Fixture tests
exercise longer-proof rescue, identical search work, shared-nominee
deduplication, explicit incumbent controls, plan/budget tampering and the refusal
to hide a failed comparison arm. Fixture costs are manufactured, not Lean data.
An initial new assertion compared complete independent receipts, including wall
time; it was corrected to compare work identities and semantic outcomes while
retaining timing observations. The final focused suite passed 85 tests.

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

This is a targeted suite, not the entire repository's tests. Automatic pytest
plugin loading stays disabled so optional plugins cannot write into the frozen
copy; the explicit repository conftest plugin still runs.

Post-archive validation passed **596 tests, 5 skipped, 89 deselected in 3.58
seconds** ([log](post-archive-regression.xml)). It adds a no-nominee/no-confirmation
control, historical trial-accounting checks, and reconstruction of the two
malformed source edits. An initial archive assertion also counted an edit
**proposed but blocked by the call cap** as a native rejection; it was corrected
to distinguish proposals from actual attempts. That initial test run is retained
in [post-archive-first-regression.xml](post-archive-first-regression.xml).

The exact post-archive command, from the repository root, was:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_ARENA_NATIVE_TESTS=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  --junitxml=papers/completion/lean_refactor_arena/evidence/solver-nomination-strata-2026-09-24/post-archive-regression.xml \
  tests/test_arena_aggregate.py tests/test_arena_report_audit.py \
  tests/test_arena_solver_balanced.py tests/test_arena_solver_pilot.py \
  tests/test_arena.py tests/test_arena_lean.py tests/test_arena_trial.py \
  tests/test_arena_pareto.py tests/test_arena_local.py tests/test_arena_solver.py \
  tests/test_arena_solver_selection.py tests/test_arena_solver_native.py \
  tests/test_solver_feedback.py tests/test_typed_terms.py \
  tests/test_proof_metrics.py tests/test_router_tuning.py \
  -k 'not real_ and not compiled_expression and not mathlib_expression and not compiler_generates'
```

All 18 copied machine-generated evidence files matched their runtime originals
byte-for-byte. The pilot implementation still matched the frozen source, and
`git diff --check` passed. These consistency checks do not reverify Lean proofs.

## Implementation changes and limits

`jevops/arena_solver_pilot.py` now binds per-arm nomination settings and the
common aggregate objective into the new opt-in profile, preserves legacy
profiles, deduplicates shared nominees, and reports a neutral no-eligible-draft
outcome without consuming confirmation work. `tests/test_arena_solver_pilot.py`
covers the orchestration and historical result, including reconstruction of
the rejected source-span edits. README and the solver guide document the new
command. No new dependencies, learned policy, external API integration or
parallel agent framework were introduced.

This trial does not establish that aggregate nomination is generally better
than dual-first nomination. Both were neutral at the same limited search
budget. Worker metric parity, broader corpus coverage, complete tactic-span
handling, production promotion and official submission remain separate work.
