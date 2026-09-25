# Strata shared-prefix specialization — 2026-09-25

This public development trial uses the recovered **169-token incumbent** for
`CallElimCorrect.extractedOldExprInVars`, not the historical 185-token comparator.
The original remains 222 tokens. Only source text is reused; earlier receipts
are not current proof or cost evidence. The profiler's hotspot is a search
hypothesis, not a prediction of savings or an edit anchor.

## Confirmed result

**`CONFIRMED_LOCAL_IMPROVEMENT`**: all **30 screening/confirmation** checks
verified, with unchanged target/type and axiom set (`propext`, `Quot.sound`).
Against the incumbent, five extra tokens buy **21.49% fewer raw heartbeats**
and **+2.77627 local combined-score points**. Against the original, the draft
has 48 fewer tokens (21.62%), 61.35% fewer heartbeats and +27.65698 local points.
These are matched-local, single-problem estimates, **not an official score**,
corpus aggregate, measured end-to-end speedup, or held-out result.

Fresh confirmation, three observations per arm/order:

| Source | Tokens | Raw heartbeats, reference-first | Raw heartbeats, candidate-first |
| --- | ---: | ---: | ---: |
| Original | 222 | 2,607,572 each | 2,607,585 each |
| Incumbent | 169 | 1,283,749 each | 1,283,762–1,283,764 |
| Explicit-support candidate | 174 | 1,007,840 each | 1,007,853 each |

The conservative descriptive gain over the incumbent remains at least
**+2.77497 points** in both orders after the frozen range/noise margin; this
is not a statistical confidence bound. Reanalysis under `strict-dual-v1`
selects nothing because the draft is longer. Keep the [169-token incumbent](incumbent.json)
and [174-token aggregate candidate](solver-0.json) distinct. There is no
production promotion or automatic continuation of search.

Actual trial use: **42/48 reserved native processes** — two controls, ten
discovery calls, twelve screening checks, eighteen confirmation checks.
Across those calls, 36 verified and six support deletions were rejected.
Unused reservations were not spent. Pilot wall time: **992.92 seconds**;
launcher including source/resource checks: **1,004.70 seconds**. Source
binding verified **UNCHANGED** before/after. Remaining capped-volume space
after the trial was **403,095,552 bytes**; no caches were removed.

The [selector audit](audit/summary.md) and [derived accounting](analysis.json)
are `CONSISTENT`, with zero new native calls and no independent proof
attestation. Runtime JSON was compared byte-for-byte with this archive.
The changed pilot and both changed test files still match the source snapshot.
The [report](report.json), [full selection measurements](selection.json),
[discovery](discovery-prefix-reference.json), [plan](plan.json),
[source binding](source-binding.json) and [manifest](source-manifest.json)
retain the exact identities, rational deltas, failures and counts.

## Frozen protocol

The existing solver pilot's opt-in `prefix-reference-v1` profile runs one
`balanced-frontier-v1` search: 16 calls, four states, depth two, one solver
site per checked source, one nominee. Native parser spans bind the complete
tactic. Every hint replacement and support deletion needs a fresh whole-proof
check, including the unchanged continuation. This is not a matched-controller
comparison or a claim of minimal support.

Nomination uses `discovery-reference-v1`, with the original's fresh token/raw
heartbeat denominators. Longer proofs may qualify only when the combined
objective improves. Fresh `aggregate-local-v1` selection checks both original
and incumbent, using a 100-raw-unit noise floor plus observed ranges. There
are two repeats/order for screening and three/order for fixed-winner
confirmation. This is not a strict-dual claim or statistical confidence bound.

Full ceiling: **48 serial native checks** = two controls + sixteen discovery
+ twelve screening + eighteen confirmation. Unused reservations are not
reallocated; no retries, adaptive search expansion or automatic promotion.
The sole declared pin is Lean **4.26.0**, Strata commit
`451e5f047bafa010d178856db76c00029bfa4d7f`.

Plan-only command (does not execute Lean):

```bash
PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
python -m jevops.arena_solver_pilot \
  --comparison prefix-reference-v1 \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent papers/completion/lean_refactor_arena/evidence/subset-triple-strata-2026-09-25/incumbent.json
```

Plan identity: `6c1945f7f3bc07d90840f6694bb330ceebfe58cee6a0d85d68c75cf4497e988e`.
Run directory:
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/prefix-reference-strata-xgev1pci`.
Read-only snapshot: **2,068 files / 55,042,716 bytes**; manifest SHA-256
`55ec25cc12d108f02c557c486a41d99fdce694cfdf16d0435eb30f335fecdaf6`;
content root `6761d558fd7170a5e38eb6c3b4cb37916117fe52e4c968d909cf0901db58dd04`.
Hashes identify bytes, not proof truth.

The CLI runs from that snapshot through an isolated Python import path, with
prepared project inputs. The child receives only PATH/HOME/LANG/LC_ALL plus
the explicit disabled-external-hooks/router flags and capped-volume TMPDIR.
The existing preparation flock, 50 GB storage cap and 100 MB runtime reserve
remain in force. No model/API calls, downloads or dependency builds are part
of this experiment. Trusted-local execution is **not an OS sandbox**.

The actual native command, cwd at the snapshot's `source` (also recorded in
[launch.json](launch.json)):

```bash
/home/barberb/.local/bin/python -I -B -c \
  'import sys; sys.path.insert(0,sys.argv.pop(1)); from jevops.arena_solver_pilot import main; raise SystemExit(main())' \
  /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/prefix-reference-strata-xgev1pci/source \
  --problem CallElimCorrect.extractedOldExprInVars --comparison prefix-reference-v1 \
  --incumbent inputs/incumbent.json --execute --max-processes 48 \
  --snapshot-manifest-sha256 55ec25cc12d108f02c557c486a41d99fdce694cfdf16d0435eb30f335fecdaf6 \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --projects inputs/projects.json \
  --elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
  --output /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/prefix-reference-strata-xgev1pci/experiment
```

Reproduction requires a new snapshot/output; existing evidence is never
overwritten or reused as fresh proof/cost authority. The exact report audit was:

```bash
env PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
python -m jevops.arena_report_audit \
  --protocol papers/completion/lean_refactor_arena/evidence/prefix-reference-strata-2026-09-25/selection-plan.json \
  --report papers/completion/lean_refactor_arena/evidence/prefix-reference-strata-2026-09-25/selection.json \
  --output-dir papers/completion/lean_refactor_arena/evidence/prefix-reference-strata-2026-09-25/audit
```

## Bounded discovery

Discovery completed in **ten native calls**: four verified requests (seed,
two query probes, one replacement) and six rejected support deletions. Its
two retained sources have 169 and 174 tokens. The complete source edit is:

```diff
-    simp [Imperative.HasVarsPure.getVars, extractOldExprVars,
-          Lambda.LExpr.LExpr.getVars] at *
+    simp only [extractOldExprVars, Imperative.HasVarsPure.getVars, Lambda.LExpr.LExpr.getVars, List.Subset.empty, List.append_assoc] at *
```

All following case proofs are byte-for-byte unchanged. The candidate source
SHA-256 is `5c629da9cec937115bac2c2ef9d55dc7e9ad3afd0c2f851f6d7e02ed4ff3311a`.
Discovery measurements were 1,283,749 raw heartbeats for the seed and
1,007,840 for the candidate. These single observations only nominate a draft;
screening and confirmation use new processes and no proof-receipt cache.

Empty support and each of the five one-entry deletions failed full replay.
Removing `List.Subset.empty` left base-case goals open. The other deletions
caused induction/append-shape continuation errors, including the `ite` case.
This establishes failure of these six edits with this fixed continuation,
not global minimality or the impossibility of repairing their dependents.
One exact duplicate suggestion was suppressed without reusing it as a new
verification event. No depth/site/state/call cap truncated this search.

## Regression/development observations

The first new-profile fixture test caught execution still using the old
module-level limits instead of the frozen profile limits. The pilot now
constructs and applies its `SolverLimits` from the validated plan for both
fixture and native paths. Legacy profiles' budgets/objectives are unchanged.

An initial broad regression invocation unexpectedly ran two legacy Lean
tests because their skip condition checked only for an installed executable.
Both failed their original-source acceptance assertions; that run was
**334 passed, two failed, one skipped**, not an offline pass. Their failure
JUnit is retained separately. The precise native failure reason was not
captured by those assertions; no successful integration claim is made.
The two tests and the cached-Mathlib test now require explicit
`JEVOPS_ARENA_NATIVE_TESTS=1` and are marked non-sealable. This is an intentional
test-execution change, not a claimed fix of those native failures.

A separate, explicit native regression then ran the same two tests from the
read-only snapshot, under the preparation lock, with **the installed Lean
4.26.0 binary directory first on PATH** (not the ambient `elan` stable shim).
Both passed in **18.33 seconds**, using all eight separately reserved compiler
invocations. The wrapper counted calls before execution and would reject a
ninth; none occurred. Its [launch](native-regression/launch.json),
[accounting](native-regression/accounting.json), [JUnit](native-regression/native.xml)
and [unchanged source binding](native-regression/source-binding.json) are
retained. No passes were sealed or reused. These eight calls are additional
regression work, not part of the 42-call optimization trial or new score
evidence. The initial ambient-toolchain failures did not reproduce on the pin;
their precise cause remains unconfirmed. The cached-Mathlib case was not run.

The wrapper invokes these exact pytest node IDs, with
`JEVOPS_ARENA_NATIVE_TESTS=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, hooks/external
router disabled, capped-volume TMPDIR, and separate output/cache/basetemp:

```text
tests/test_solver_feedback.py::test_real_lean_simp_feedback_replays_with_exact_envelope
tests/test_solver_feedback.py::test_real_grind_query_does_not_accept_longer_hint
```

The corrected offline command:

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-prefix-reference-tests/cache \
  --junitxml=/tmp/jevops-prefix-reference-tests/regression.xml \
  tests/test_arena_solver_pilot.py tests/test_arena_solver.py \
  tests/test_solver_feedback.py tests/test_solver_spans.py \
  tests/test_arena_pareto.py tests/test_arena_aggregate.py -q
```

Observed **334 passed, three skipped in 24.91 seconds**, zero reused seals,
328 fresh passes sealed. These are targeted offline tests, not native proof
checks or full-repository coverage.

## Next bounded hypothesis and limits

Test dependency-aware repair after removing append normalization, or narrow
which hypotheses the prefix simplifies. Both require a new frozen trial with
fresh source-bound observations; the six failed fixed-continuation deletions
cannot be relabeled successful. No such follow-up was run here. Preserve the
169-token strict baseline and 174-token aggregate baseline when comparing new
drafts. Broader task coverage, held-out generalization, organizer-worker metric
parity and production/security release gates remain open. This trial used no
model, training, dependency build/download, or official submission.
