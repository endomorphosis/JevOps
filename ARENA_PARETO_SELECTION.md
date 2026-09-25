# Token and heartbeat selection with fresh confirmation

`python -m jevops.arena_pareto` implements the first selection increment of the
two-objective plan. It reuses `arena_trial.run_trial`, `ArenaEvaluator` and
`NativeLeanVerifier`; it does not change the native checker or the legacy
router's scalar Arena objective. It is a bounded batch selector, not a continuous
search worker, learned optimizer, production promotion mechanism or official
competition worker.

## Admission and selection

Provide a fixed batch of drafts and optionally an explicit current incumbent.
The unchanged original is always a control. An incumbent is untrusted input,
not a historical receipt: it receives fresh checks alongside every candidate.
Existing bounded slicing/simplification proposal generators can supply drafts;
their source text and provenance carry no verification authority.

Every arm is checked on every declared version, both branch orders and every
scheduled repetition. There are two to five repetitions per phase. Selection
requires a complete screening schedule; timeouts and unavailable infrastructure
cannot disappear from the denominator. Rejected alternatives remain recorded.
An invalid incumbent is an incomplete experiment, not a verified fallback.

A candidate can dominate another only when:

- Its reference-compatible source token count is no greater.
- It adds no transitive axioms relative to that proof. Each admitted arm must
  also add no axioms relative to the original, even within the fixed allowlist.
- In every version/order stratum, its raw heartbeat range is strictly lower
  by more than the larger observed range, or all raw counts in both arms are
  exactly equal. Overlapping variable ranges mean **unknown**, not equivalence.
- At least one token or heartbeat comparison is strictly better.

This is a conservative descriptive rule, not a statistical equivalence or
significance test. It may abstain on real improvements. It does not establish
future performance, global minimality, or reductions in wall time or proof DAG
size. The latter remain separate, unmeasured diagnostics in this selector.

The observed frontier retains admissible alternatives not demonstrably dominated
by another arm, including shorter/slower and longer/faster trade-offs. A selected
draft must dominate **both the original and the current incumbent**. Eligible
frontier members are ranked by tokens, then worst per-stratum mean heartbeat
ratio to the incumbent, then label. These tie-breakers cannot bypass admission.
Equal-cost candidates do not replace the incumbent.

### Strict improvement in both costs (opt-in)

`--selection-objective strict-dual-v1` requires **strictly fewer proof tokens
and strictly lower raw heartbeats in every version/order stratum**, relative
to both the original and the explicit incumbent. An equal heartbeat count or
equal token count fails this gate even if the other cost improves. The default
`pareto-v1` retains the non-increasing/one-strict behavior described above;
neither option changes the general router's `arena-v1` score mode.

`--heartbeat-noise-floor-raw N` sets an integer, nonnegative floor in raw
heartbeat units, not milliseconds or displayed heartbeat thousands. Strict
separation must exceed the maximum of this floor and both arms' observed
ranges. Zero preserves the existing range-only comparison; it does not bypass
the variation check. Set a control-derived floor before searching, not after
seeing candidate results. This is still a descriptive filter, not significance.

The objective and floor are included in the protocol/content hash and applied
unchanged in both screening and confirmation. Draft files cannot override them
or supply authoritative costs. The ordinary Pareto frontier remains available
for discovery; it does not authorize a strict recommendation. Thus a frontier
can contain promising alternatives while the checked incumbent is retained.

Programmatic callers pass `selection_objective="strict-dual-v1"` and
`heartbeat_noise_floor_raw=N` to `selection_plan`/`run_selection`. Invalid
objectives, booleans, negative or noninteger floors fail before verifier work.
No saved-report import, production promotion, cold single-branch isolation,
term-DAG gate or OS sandbox is added by this selection criterion.

## Aggregate local score (opt-in)

`--selection-objective aggregate-local-v1` permits longer/faster and
shorter/slower trade-offs. It does **not** change the default `pareto-v1`, the
`strict-dual-v1` gate, or the router's existing `arena-v1` mode. All declared
pins, orders and repetitions must still verify the exact target without axiom
growth. A score cannot authorize an invalid or unavailable proof.

The public Arena formula combines reference-normalized token reduction,
reference-normalized default-pin heartbeat reduction and compatibility with
equal weights. This local mode fixes compatibility at 100% through the hard
all-pin gate. It uses the **first declared pin** for cost; later pins are
compatibility checks, not extra heartbeat objectives. Both branch orders must
independently improve. Compared with original or incumbent `b`, candidate `a`
has this unrounded local delta, in percentage points:

```text
100/3 * ((tokens_b - tokens_a)/tokens_original
       + (mean_raw_b - mean_raw_a)/mean_raw_original)
```

The denominators come from the freshly checked original in the same phase and
order. Published heartbeat fields are not mixed with local raw measurements:
worker metric parity remains unconfirmed. The report contains exact rational
numbers, `official_score: null`, and scope `matched-local-primary-pin`.
This is not a corpus-wide score, a rounded leaderboard prediction, or evidence
of generalization beyond these exposed development tasks.

Selection uses a conservative descriptive margin, **not a confidence interval**:
subtract the largest of the predeclared raw-unit floor and the three observed
heartbeat ranges from `min(raw_b) - max(raw_a)`. Normalize a nonnegative result
by `max(raw_original)`, a negative result by `min(raw_original)`, then add the
exact token term and multiply by `100/3`. This lower descriptive delta must be
strictly positive against both original and incumbent in both primary-pin
orders. A zero reference denominator means abstention, not a replacement with
one. Secondary-pin cost regressions are reported but do not veto this expressly
primary-pin objective; any secondary-pin verification failure still does.

Eligible candidates rank by greatest worst-order conservative delta against
the incumbent, then mean nominal delta, token count and label. The ordinary
all-pin Pareto frontier is still reported but is not an aggregate gate.
Fresh, fixed-winner confirmation applies the same rule with new controls and
no retries or second-place fallback. Tests include winning trade-offs, neutral
and losing alternatives, noisy measurements, zero denominators, broken proof
receipts, unavailable pins and failed confirmation.

```bash
python -m jevops.arena_pareto --plan --problem PROBLEM \
  --candidate shorter.json --candidate longer.json \
  --selection-objective aggregate-local-v1 --heartbeat-noise-floor-raw 100 \
  --repetitions 2 --confirmation-repetitions 3 --output-dir /prepared/new-plan
```

For one pin and no separate incumbent this reserves 12 screening plus 12
confirmation requests. Use `--run --max-calls 24` with exact prepared projects,
a frozen source copy and the preparation lock for native execution. It does
not reuse the saved candidates' previous receipts.

The [first frozen Physlib comparison](papers/completion/lean_refactor_arena/evidence/solver-aggregate-pilot-2026-09-24/README.md)
completed all 24 native checks. It confirmed the 1377-token specialization over
the 1372-token original: about 8.63% lower raw heartbeats and +2.755 unrounded
local combined-score percentage points. Reanalysis of that same screen under
the unchanged Pareto/strict-dual rules selects nothing. This is a comparison of
selection criteria on saved candidates, not a new discovery-method benchmark.

## Independent confirmation protocol

Before constructing a confirmation verifier, the selected source, screening
observations and full plan are bound into a selection commitment. Only that
winner proceeds; no second-place fallback, new proposal, retry or adaptive
repetition is allowed after viewing confirmation results.

Confirmation starts fresh verifier instances and processes, rechecks the
original and any explicit incumbent, and applies the same gates. Receipt caches
are disabled. Dependency contexts and all non-order settings must agree across
phases. Every version context is revalidated at the end of its phase, including
versions measured early. Selector and trial source files must remain unchanged
across the run. These hashes identify files; they are not signatures or loaded
Python bytecode attestations.

`CONFIRMED_LOCAL_IMPROVEMENT` returns a recommendation with source and provenance.
It never overwrites a proof or updates production memory. `UNCONFIRMED` retains
the incumbent after a conclusive failed confirmation; `INCOMPLETE` reports missing
or stale evidence. `NO_IMPROVEMENT` is a bounded-search outcome, not proof of
optimality. Synthetic tests use `FIXTURE_CONFIRMED`, report zero native processes
and cannot return a native recommendation. Every report has `promoted: false`,
`training_enabled: false` and `official_score: null`.

The injected verifier factory and filesystem are trusted infrastructure, not
LLM-controlled code. There is no API for promoting from a saved report. This
module does not add an OS sandbox: use stable trusted prepared projects, and do
not run arbitrary generated metaprograms in a privileged environment.

## Budgets and reports

The complete worst-case screening plus confirmation request budget must be
reserved before constructing any verifier. Each phase retains the existing
128-request bound, at most eight non-control arms and eight version pins.
There are at most 256 requests total. Native process counts, reserved requests
and fixture invocations remain separate. Declining to confirm an unpromising
batch leaves its reserved confirmation capacity unused.

The CLI writes `protocol.json` before native execution and generates
`report.json` and `summary.md` on completion. Stdout is a short status/count/path
object; progress goes to stderr. Output directories must be new. No large
reports are generated in model token space. There is no crash-resume guarantee;
an interrupted run may have only its protocol file and cannot be promoted.

Draft JSON uses exactly `name`, `label`, `source`, and `provenance`. Extra fields
such as `theorem_ok`, claimed costs or rewards are rejected. `--incumbent` uses
the same schema. Without it, the original is the incumbent.

```bash
# Plan only: no Lean process, dependency preparation, provider or model call.
python -m jevops.arena_pareto --plan --problem Core.InitsUpdatesComm \
  --candidate papers/completion/lean_refactor_arena/evidence/core-hlen2-repair-draft.json \
  --selection-objective strict-dual-v1 --heartbeat-noise-floor-raw 0 \
  --repetitions 2 --confirmation-repetitions 2 --output-dir /prepared/new-plan

# This is the historical manual repair, not a new search discovery or blind task.
# Three pins × two orders × two repeats × two arms × two phases = 48 requests.
python -m jevops.arena_pareto --run --problem Core.InitsUpdatesComm \
  --projects /prepared/projects.json --elan-home /prepared/elan \
  --candidate papers/completion/lean_refactor_arena/evidence/core-hlen2-repair-draft.json \
  --selection-objective strict-dual-v1 --heartbeat-noise-floor-raw 0 \
  --repetitions 2 --confirmation-repetitions 2 --max-calls 48 --timeout 120 \
  --progress --output-dir /prepared/new-confirmation

# Separate stdlib integration control; this is NOT an Arena benchmark.
python -m jevops.arena_pareto --smoke --tag v4.34.0 --max-calls 20 \
  --selection-objective strict-dual-v1 \
  --progress --output-dir /prepared/new-smoke

pytest -q --test-seal=off tests/test_arena_pareto.py tests/test_arena_trial.py
```

Return code 2 means incomplete evidence, 0 means a conclusive run or offline
plan—not necessarily an improvement. Inspect the explicit status and recommendation.
Missing projects never trigger downloads, builds or version substitutions.
Coordinate native runs with the prepared workspace's `single-build.lock`, as
in [controlled trials](ARENA_CONTROLLED_TRIALS.md). The CLI does not acquire a
global lock itself. A failed nonblocking lock acquisition means no native
experiment started; it is not a proof failure.

## Next integration boundaries

The general router still has its existing separately named score-selection mode;
this strict two-objective selector has not silently replaced it. A first narrow
diagnostic-guided arity repair now feeds this batch interface (below); broader
syntax/dependency-aware repair and trajectory collection still need work. CE/cosine training,
JeV/NCA feedback, sealed holdouts and final production promotion remain separate
gates; this module does not claim to have implemented them.

## Diagnostic-guided argument/goal repair

`--repair-from-trial rejected-trial.json` treats an old native trial strictly
as a source of **unverified proposals**, not cached successes. The frozen
problem record, rejected source, request identity, target and version/context
must agree. Repeated copies of the same diagnostic yield one source draft.
Malformed, mismatched or oversized reports cannot create an experiment output.
`--proposal-cap` bounds the repair drafts; zero generates none.

The current repair supports one precise failure shape: a Lean `Function expected
at` error identifies an overapplied parenthesized `apply`/`refine`/`exact` call.
It requires a unique source anchor with a final explicit `?_`, and one explicit
dot-bullet subgoal block per explicit hole. It removes that trailing argument
and its last associated block together. Other error types, ambiguous anchors,
comments, unsupported nested arguments or mismatched block counts abstain.

This is a bounded source/layout heuristic informed by an elaborator diagnostic,
**not a Lean parser, full dependency analysis, or a proof**. In particular,
implicit arguments or goal ordering can invalidate its inferred association.
Only fresh whole-proof checking can accept the result. A timeout is not a repair
signal, and a passing test or `theorem_ok` field is not admission evidence.

The saved Core rejection reconstructs the prior manual Hlen2 repair without
loading the manual answer into the generator. It is known warm-up/development
data; reproducing it does not establish unseen-task generalization. The CLI
below only schedules a new 48-request experiment. It does not rerun or promote
the reconstructed proof:

```bash
python -m jevops.arena_pareto --plan --problem Core.InitsUpdatesComm \
  --repair-from-trial papers/completion/lean_refactor_arena/evidence/native-controlled-core-2026-09-22.json \
  --proposal-cap 2 --selection-objective strict-dual-v1 \
  --repetitions 2 --confirmation-repetitions 2 --output-dir /prepared/new-repair-plan
```

`diagnostic_repair_candidates` in `arena_trial.py` exposes the same operation
programmatically. `proof_slicing.arity_repair_variants` implements the restricted
edit. There is no automatic retry chain, model call, training or production
memory update. Pass the resulting `Candidate` objects through `run_selection`
with a full fresh budget; diagnostics never substitute for receipts.

## Isolate long experiments from live checkout edits

Use a new source bundle and an isolated Python interpreter for long runs. The
snapshot utility creates read-only copies, records exact file hashes, detects
source changes during capture, and refuses to overwrite existing destinations.
Run the standalone utility to avoid importing the mutable package during setup:

```bash
python jevops/arena_snapshot.py create --repo /absolute/JevOps \
  --include jevops --output-dir /owned/preparation/work/new-runtime
# Retain manifest_sha256 from this output independently of the snapshot.
python jevops/arena_snapshot.py verify --root /owned/preparation/work/new-runtime \
  --manifest-sha256 <retained-manifest-sha256>
```

Choose `--include` paths deliberately: selected regular files are copied, not
only files tracked by Git. Do not include credentials or unrelated user data.
Prepared Lean projects/toolchains and Python itself are not duplicated; native
dependency/context validation still applies. This is not an OS sandbox or an
atomic snapshot against hostile filesystem mutation.

Launch from the fixed bundle with `python -I -B` and an explicit package path
(suppressing ambient `PYTHONPATH`, user site packages and bytecode writes):

```bash
flock -n /owned/preparation/single-build.lock \
  python -I -B -c 'import runpy, sys; sys.path.insert(0, sys.argv.pop(1)); runpy.run_module("jevops.arena_pareto", run_name="__main__")' \
  /owned/preparation/work/new-runtime --run --problem Core.InitsUpdatesComm \
  --corpus /absolute/JevOps/papers/completion/lean_refactor_arena/data/benchmark_data_warmup.jsonl \
  --projects /owned/preparation/work/projects-prepared-20.json --elan-home /owned/preparation/work/elan \
  --candidate /absolute/JevOps/papers/completion/lean_refactor_arena/evidence/core-hlen2-repair-draft.json \
  --proposal-cap 0 --selection-objective strict-dual-v1 --repetitions 2 \
  --confirmation-repetitions 2 --max-calls 48 --timeout 120 --progress \
  --output-dir /owned/preparation/work/new-confirmation
```

Keep output and temporary files outside the read-only bundle and within the
50 GB preparation allowance. Verify the retained bundle again after the run;
do not disable the native source-change guard. When auditing an older bundle,
use its bundled verifier utility/manifest format, not an incompatible newer
utility in a concurrently edited checkout.

## Strict-mode verification, 2026-09-22

The [saved native stdlib control](papers/completion/lean_refactor_arena/evidence/native-strict-dual-smoke-2026-09-22.json)
finished `CONFIRMED_LOCAL_IMPROVEMENT`: eight screening and twelve confirmation
executions, all VERIFIED, on installed Lean v4.34.0. Source identity stayed
unchanged throughout. The fixed `True` proof went from 15 to 3 proof tokens:
raw heartbeats were 10,424 to 4,498 in reference-first order and 10,484 to 4,535
in candidate-first order. Each stratum repeated exactly in this run. It is a
small integration control, **not an Arena task, search discovery, statistical
claim, held-out result or wall-time speedup**. No model calls or production
promotion occurred. The full JSON SHA-256 is
`996c5d4dd56d8e11c9a16b05489a6c97d6a2d7be9f970250d0504547df57bcd3`.

Actual native command (the output directory must be new for a rerun):

```bash
flock -n /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/single-build.lock \
  env TMPDIR=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp \
  python -m jevops.arena_pareto --smoke --tag v4.34.0 \
  --elan-home /home/barberb/.elan --selection-objective strict-dual-v1 \
  --heartbeat-noise-floor-raw 0 --max-calls 20 --timeout 90 --progress \
  --output-dir /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/strict-dual-smoke-2026-09-22
```

The first lock acquisition was declined without starting Lean. An existing
Core confirmation run held the lock and overlapped the selector edits; its
48-process report returned `INCOMPLETE: implementation_changed_during_selection`
with no recommendation. Those measurements are not a clean confirmation of
this implementation. The guard was not bypassed and the experiment was not
stopped or overwritten. The separate native control above started only after
that run released the lock.

Offline tests cover strict/equal/regressing costs, every version/order,
incumbent and original comparisons, exact noise-floor boundaries, both phases,
invalid policy fields, axiom expansion, forged receipts, missing pins, stale
contexts, zero budgets and compatibility with the default Pareto mode. Saved
receipt tests audit bookkeeping; they never re-execute or admit a historical
proof. OS sandboxing, cold single-branch confirmation and automatic production
promotion are not covered by an implementation claim here.

Commands run after the final code/test changes:

```bash
python -m pytest -q --test-seal=off tests/test_arena.py tests/test_arena_pareto.py tests/test_arena_trial.py
# 250 passed in 1.11s.

python -m pytest -q -rs --test-seal=off tests/test_arena.py tests/test_arena_pareto.py tests/test_arena_trial.py tests/test_arena_lean.py tests/test_arena_module_audit.py tests/test_router_tuning.py tests/test_solver_feedback.py tests/test_candidate_audit.py tests/test_scoped_evaluation.py
# 390 passed, 100 skipped in 69.62s.
```

The skips are 99 opt-in native tests and one cached-Mathlib test. The separate
20-process native control above was explicitly run; the full repository test
suite was not. The offline Core strict-mode plan also ran successfully and
reserved 48 requests for two repeats in each of its two phases, without
executing Lean. No dependency downloads or builds were started for this change.

## Clean Core confirmation and repair follow-up, 2026-09-23

The [complete native report](papers/completion/lean_refactor_arena/evidence/native-strict-dual-core-2026-09-23.json)
finished `CONFIRMED_LOCAL_IMPROVEMENT`: **24 screening plus 24 fresh confirmation
requests, all VERIFIED**, for `Core.InitsUpdatesComm`. All three required Lean
pins, both branch orders and two repetitions per phase were checked. The final
source/context revalidation passed; receipt caching was disabled. The exact
report SHA-256 is `b845b1d9ee9f458e3d504b88e4621e767430505e1e5f8d459bee9d65780d49d0`.

The predeclared, manually seeded `repair-Hlen2-induction-arity` candidate has
**224 → 216 proof tokens (3.57% fewer)**. Its checked theorem type and transitive
axiom set match the reference (`Classical.choice`, `Quot.sound`, `propext`).
Confirmation raw heartbeat observations were:

| Lean | Order | Unchanged control, two runs | Repair, two runs | Reduction in stratum mean |
| --- | --- | --- | --- | ---: |
| v4.29.1 | reference-first | 4,227,568; 4,227,568 | 2,625,874; 2,625,874 | 37.89% |
| v4.29.1 | candidate-first | 4,227,600; 4,227,600 | 2,625,906; 2,625,906 | 37.89% |
| v4.27.0 | reference-first | 4,657,775; 4,657,774 | 2,732,961; 2,732,961 | 41.32% |
| v4.27.0 | candidate-first | 4,657,791; 4,657,792 | 2,732,978; 2,732,978 | 41.32% |
| v4.26.0 | reference-first | 4,689,118; 4,689,118 | 2,701,014; 2,701,014 | 42.40% |
| v4.26.0 | candidate-first | 4,689,131; 4,689,133 | 2,701,027; 2,701,027 | 42.40% |

Both phases passed the strict separation gate on every stratum; the full report
retains screening observations too. These are descriptive heartbeat reductions,
not wall-time speedups, independent statistical samples or an official score.
This remains one known warm-up task, not a blind/held-out search result. No model
call, training, production promotion, dependency download or build occurred.

The new diagnostic helper independently reconstructs the candidate's exact
source bytes from the saved **rejected** deletion trial, without reading the
manual answer. The regression test reads that answer only after generation.
The native run itself was launched with the manual seed before the helper was
implemented: it must not be relabeled as an automatic search discovery. A repair
CLI plan was also executed successfully: 48 requests planned, zero Lean processes.

### Fixed runtime provenance and actual command

The live checkout continued changing while this experiment ran. Its independent
source bundle contained 103 Python/Lean files (2,864,311 bytes), with snapshot ID
`16ab81c067fc7db7c7cfb8e7c92d0e9222010d0fa6650f6fbaf34c25e9c93e21`.
The [captured manifest](papers/completion/lean_refactor_arena/evidence/native-strict-dual-core-2026-09-23.snapshot.json)
records every file hash. Its bundled verification utility confirmed the bundle
unchanged both during the run and after completion; this is file identity,
not proof verification or filesystem authentication. The bundle predates the
new repair helper and the subsequently revised live snapshot utility. Audit
this historical bundle with its own utility, not the newer manifest API.

The following command actually completed under the workspace's exclusive lock.
Use a new output directory for any rerun. All paths stayed within the authorized
prepared workspace; its measured usage after the run was 20,753,326,080 bytes,
within the 50 GB allowance.

```bash
flock -n /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/single-build.lock \
  env TMPDIR=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp \
  python -I -B -c 'import runpy, sys; sys.path.insert(0, sys.argv.pop(1)); runpy.run_module("jevops.arena_pareto", run_name="__main__")' \
  /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/core-strict-20260923-JPNt3z/runtime \
  --run --problem Core.InitsUpdatesComm \
  --corpus /home/barberb/lift_coding/JevOps/papers/completion/lean_refactor_arena/data/benchmark_data_warmup.jsonl \
  --projects /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/projects-prepared-20.json \
  --elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
  --candidate /home/barberb/lift_coding/JevOps/papers/completion/lean_refactor_arena/evidence/core-hlen2-repair-draft.json \
  --proposal-cap 0 --selection-objective strict-dual-v1 --heartbeat-noise-floor-raw 0 \
  --repetitions 2 --confirmation-repetitions 2 --seed 17 --max-calls 48 --timeout 120 --progress \
  --output-dir /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/core-strict-20260923-JPNt3z/confirmation

python -m jevops.arena_pareto --plan --problem Core.InitsUpdatesComm \
  --repair-from-trial papers/completion/lean_refactor_arena/evidence/native-controlled-core-2026-09-22.json \
  --proposal-cap 2 --selection-objective strict-dual-v1 \
  --repetitions 2 --confirmation-repetitions 2 \
  --output-dir /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/core-strict-20260923-JPNt3z/diagnostic-plan
```

These results do not add corpus coverage: the historical union remains 20 of
36 verified reference-version checks, with 16 unverified. General dependency
repair, held-out optimization, cold single-branch measurement, OS sandboxing
and production promotion remain follow-up work.

### Follow-up regression commands and observed results

```bash
python -m pytest -q --test-seal=off tests/test_arena_pareto.py tests/test_arena_trial.py tests/test_arena_snapshot.py tests/test_proof_slicing.py -k 'not real_kernel_checked_slicing'
# 229 passed, 1 deselected in 0.94s.

python -m pytest -q -rs --test-seal=off tests/test_arena.py tests/test_arena_pareto.py tests/test_arena_trial.py tests/test_arena_snapshot.py tests/test_proof_slicing.py tests/test_arena_lean.py tests/test_arena_module_audit.py tests/test_router_tuning.py tests/test_solver_feedback.py tests/test_candidate_audit.py tests/test_scoped_evaluation.py -k 'not real_kernel_checked_slicing'
# 455 passed, 100 skipped, 1 deselected in 67.46s.
```

The 100 skips comprise 99 opt-in native checks and one cached-Mathlib test.
The older implicitly enabled `real_kernel_checked_slicing` integration test was
deliberately deselected to keep this regression command offline and avoid an
overlap with the isolated native experiment. The complete repository suite was
not run. Native coverage above is the separately executed 48-request trial.

New tests cover the precise argument/goal edit, Unicode identifiers and layout
bounds; ambiguous/unsupported diagnostics and stale source bindings; repeated
rejection deduplication; wrong record/context/receipt input; timeout abstention;
fresh CLI budget planning; and both saved native reports' request, target,
source, axiom, plan, commitment and strict-selection bookkeeping. Historical
receipt tests are not current proof admission. Source-bundle tests exercise
the current snapshot utility, not a retroactive change to the captured runtime.
