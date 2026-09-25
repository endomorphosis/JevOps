# Controlled local Arena trials

`jevops.arena_trial` measures fixed candidate proofs through the existing
`ArenaEvaluator` and `NativeLeanVerifier`. It is an experiment runner, not a new
agent framework, model, optimizer, or replacement proof checker. It reuses
`tactics.drop_redundant_simp_at`, `tactics.drop_rename_i`, and
`proof_slicing.deletion_variants` when those strategies are explicitly selected.
Their edits are heuristic proposals; only native verification admits a proof.

For a new draft, use `--candidate draft.json` with exactly `name` (the corpus
problem), `label`, `source`, and `provenance`. This is distinct from the
`--seed-candidate` historical regression format. The draft has no verification
authority: extra flags such as `theorem_ok` are rejected, and the normal typed
candidate bounds, fixed schedule and native admission apply. A manual
diagnostic-guided repair is labeled manual, not a learned or automatic result.

`--strategy proof_slice_unused_have` selects single-line `have` deletions from
the existing bounded slicer when the local ASCII name has no explicit use in
the remaining text. This lets a small candidate cap examine hypothesis cuts
instead of only the coarse case-block cuts at the front of the slicer's search.
It is **not** dependency analysis: `simp_all`, `assumption` and other contextual
tactics may still need the hypothesis. Native rejection is an expected result,
not evidence against the theorem. The slicer's exclusions for comments, quoted
text and oversized proofs still apply. Multiline declarations are not selected.

The motivation is an observed problem, not a hypothetical score improvement:
unchanged references sometimes had different heartbeat counts in the two
branches of the baseline driver. Comparing a candidate's second-branch count
with a reference's first-branch count confounds source changes with order and
process-cache effects. This runner records unchanged controls and both orders.

## Commands

These use an already prepared cache. No dependency downloads or builds occur.
Replace the state-root path with the actual local harness cache.

```bash
# Inventory and a reproducible schedule; no Lean execution.
python -m jevops.arena_trial --plan \
  --problem CallElimCorrect.substOldPostSubset \
  --state-root /prepared/track1-lake \
  --seed-candidate tests/fixtures/kernel_refactor_local_best.json \
  --strategy drop_redundant_simp_at --proposal-cap 1

# Four fresh checks per arm: 2 repetitions x 2 branch orders, on one required pin.
# The arms are control, explicit historical seed, and the heuristic proposal.
python -m jevops.arena_trial --run \
  --problem CallElimCorrect.substOldPostSubset \
  --state-root /prepared/track1-lake \
  --seed-candidate tests/fixtures/kernel_refactor_local_best.json \
  --strategy drop_redundant_simp_at --proposal-cap 1 \
  --repetitions 2 --seed 17 --max-calls 12 --timeout 90 \
  --progress --output /prepared/new-trial.json

python -m pytest -q --test-seal=off tests/test_arena_trial.py
JEVOPS_ARENA_NATIVE_TESTS=1 python -m pytest -q --test-seal=off tests/test_arena_lean.py
```

`--projects` is an alternative to `--state-root`, with the same explicit binding
format as [the native adapter](ARENA_NATIVE_VERIFIER.md). `--max-calls` defaults
to zero. JSON goes to stdout; optional progress goes to stderr. `--output`
refuses overwriting an existing evidence file. Reports are saved on completion;
there is no crash-resume or checkpoint/replay guarantee for an interrupted trial.
Binding/context preparation failures now retain the planned samples in an
`INCOMPLETE` report: subprocess timeouts are `TIMEOUT`, missing capabilities
are `UNAVAILABLE`, and operating-system failures are `ERROR`. These carry no
verification receipt and consume no native-call units when preparation failed
before invocation. Identity checks are not relaxed or retried implicitly.
The supplied seed is a **historical regression**, not an unseen task or a newly
discovered proof. No seed is automatically loaded from production memory.

## Design and identity

The fixed schedule contains every declared problem version, both branch orders,
each repetition, and every candidate plus the unchanged control. Candidate
ordering within each block and the order of the two blocks are seeded and
reproducible. The budget does not depend on which candidate looks promising.
Missing environments remain explicit schedule entries. A partial version matrix
is never silently reduced to the installed subset or called 100% compatibility.

The native driver starts both proof branches from the same immutable prefix
environment, with the target absent. `candidate-first` reverses elaboration
order but never provides the candidate theorem to the reference branch or vice
versa. Exact target/type and transitive-axiom checks still apply. Branch order
is bound into verifier options and checked against the native response. The
default native-adapter order remains `reference-first`.

Paired order contexts must match in source, target, dependencies, verifier,
axiom policy and every option except order. Changed code/dependencies invalidate
observations through the existing admission boundary; no calibration drift is
silently accepted by score-aware selection. The controlled runner deliberately
uses uncalibrated contexts with no fixed scalar heartbeat denominator: it
consumes validated receipts, not `ArenaEvaluator`'s scalar scores. It does not
relax the separate `.calibrate()` / `.evaluator()` router path.

Every sample gets a fresh process. Receipt caching is disabled even for repeated
unchanged controls. Content-identical requests retain identical request IDs,
while distinct repetition/order slots have distinct sample IDs. This records
separate executions; a cache hit is not counted as one. Fresh verifier instances
are required for each pin/order. File hashing may use an explicitly shared
per-run `Fingerprinter`, but this is not cached proof or cached timing evidence.

Default v1 plans still reject identical source bytes across arms. The Python
API's explicit `allow_identical_sources=True` policy emits a v2 plan for fixed
policy ablations (including unchanged fallbacks). Labels remain unique, source
identities are recorded, and every slot is measured afresh. Identical outputs
are not counted as independent discoveries. The CLI/default v1 behavior and
historical plan identities are unchanged.

## Outcomes and costs

`COMPLETE` means all scheduled observations are conclusive and all controls
verified. Individual candidate arms may be `REJECTED`; that does not disprove the
target theorem. Missing bindings, invalid contexts, failed controls, timeouts
and budget exhaustion make the experiment or affected arm `INCOMPLETE`.
Per-arm reports retain every required pin, successfully checked pins, token
counts, raw heartbeat observations, and the context-bound verification receipts.

For each pin/order, the runner reports all control/candidate raw counts, medians
and paired differences. A `LOWER` observation requires at least two repetitions,
nonoverlapping ranges, and separation greater than the larger observed range.
This is an explicitly conservative **descriptive rule**, not a significance
test, calibrated probability, latency guarantee, or claim about future tasks.
`LOWER_IN_BOTH_ORDERS` requires that rule in every required pin/order stratum.
Shorter but slower, overlapping, neutral and unavailable outcomes are retained.
Longer candidates are not rejected merely for being longer.

`observed_pareto_improvement` means fewer reference-compatible source tokens
and lower observed heartbeats under those full-coverage controls. It is not an
Arena score or an automatic promotion. `promoted` and training are always false;
`official_score` and `local_combined_pct` are always null. The native heartbeat
method still lacks organizer-worker parity. No API latency/dollars or model
quality are inferred from offline fixtures.

The integer request budget is reserved **before** evaluation, including intake
and infrastructure failures. Actual verifier invocations and native processes
are counted separately. An invocation can elaborate two proof branches; it is
not one declaration. A mocked `offline_fixture` run reports zero native processes
and labels its synthetic invocation counts explicitly. Limits: eight candidate
arms, eight pins, five repetitions, 128 request units, and the adapter's existing
source/output/heartbeat/wall-time bounds. Preparation/fingerprint work is outside
the native process count. The runner does not implement memory, disk or currency
quotas, cross-process ownership, trained dynamics, or an OS sandbox. Run trusted
inputs in stable prepared projects; imported Lean metaprograms can perform IO.

## What this does not establish

One warm-up problem, two repeats, and a hand-written transform do not demonstrate
generalization, corpus-wide improvement, superiority over another solver, or a
global minimum. Historical seeded proofs need separate reporting from new
search discoveries. Remaining pinned environments, larger preregistered matched
task sets, independent holdouts and organizer metric calibration are still
required before claiming to beat the Arena.

The [recorded Strata pilot](papers/completion/lean_refactor_arena/evidence/native-controlled-strata-2026-09-22.json)
completed twelve native checks. The historical seed measured 313 → 237 tokens
and about 1.68% lower median raw heartbeats in both orders; the existing
simplification transform measured 313 → 289 tokens and about 0.20% lower raw
heartbeats. These describe one warm-up theorem with two repeats per order, not
a new general-purpose result. No candidate was automatically promoted.

The [Core hypothesis-deletion trial](papers/completion/lean_refactor_arena/evidence/native-controlled-core-2026-09-22.json)
completed 36 native checks over all three required Lean versions, both orders,
and two repetitions. All 12 controls verified; all 24 candidate checks rejected.
Deleting `Hk` or `Hlen2` shortened the text from 224 to 213 or 219 tokens, but
neither draft was an accepted proof, so those are **not optimization gains**.
The diagnostics identify a changed induction-hypothesis argument count; the
unchanged call supplies too many arguments. The Hk cut also breaks `simp_all`.
This motivates a separately labeled repair experiment, not calling either
rejection a theorem counterexample or treating an unused name as a dead premise.

Report `runner_sha256` is the source file's hash at report emission, not an
attestation of loaded Python bytecode. Small preparation-error handling edits
landed while the deletion trial was in flight; the fixed candidate schedule and
native verifier boundary were unchanged. The receipts bind the actual source,
version and verifier context. Saved-report tests audit that bookkeeping without
claiming to re-execute the historical proofs.

### Diagnostic-guided repair: a new measured warm-up improvement

The [manual repaired draft](papers/completion/lean_refactor_arena/evidence/core-hlen2-repair-draft.json)
removes `Hlen2`, changes `(ih Hinit ?_ ?_).2.2` to `(ih Hinit ?_).2.2`, and
removes the corresponding last `. simp_all` goal block. The
[separate repaired trial](papers/completion/lean_refactor_arena/evidence/native-controlled-core-repair-2026-09-22.json)
completed **24/24 verified checks**: three exact version pins, two branch
orders, two repetitions, and two arms (unchanged control and repaired proof).
The runner and native boundary source stayed unchanged during this repaired run.

The proof is **224 → 216 tokens (3.57% shorter)**. Observed median raw heartbeat
reductions, comparing against controls in the same version/order, were:

| Lean pin | Reference-first | Candidate-first |
| --- | ---: | ---: |
| v4.29.1 | 37.8869% | 37.8866% |
| v4.27.0 | 41.3248% | 41.3246% |
| v4.26.0 | 42.3983% | 42.3981% |

These are heartbeat reductions, **not wall-time speedups**, API savings, a
statistical significance claim or an organizer score. The candidate was manually
adapted after seeing diagnostics on this warm-up problem; it is not held-out,
model-generated, trained or an automatic search discovery. No production proof,
shared project, training memory or promotion flag was changed. The result
supports continuing a compiler-guided deletion-and-repair experiment, not a
claim that JevOps already beats the full Arena.

Reproduce with the prepared three-pin project manifest and isolated Elan home:

```bash
flock -n /owned/preparation/single-build.lock \
  env TMPDIR=/owned/preparation/work/tmp \
  python -m jevops.arena_trial --run --problem Core.InitsUpdatesComm \
  --projects /owned/preparation/work/projects-prepared-20.json \
  --elan-home /owned/preparation/work/elan \
  --candidate papers/completion/lean_refactor_arena/evidence/core-hlen2-repair-draft.json \
  --proposal-cap 0 --repetitions 2 --seed 17 --max-calls 24 --timeout 120 \
  --progress --output /owned/preparation/work/new-core-repair-trial.json
```
