# JevOps

TypeSafe / Jev **kernel**, split from Lean Refactor Arena and other papers.

The Jev kernel is a **gate**, not a proof authority. Optional refactoring and
autoencoder modules propose Lean candidates; only the consuming Lean/Lake
verifier can admit them. The generic kernel keeps that verifier injectable.

## Layout

| Module | Job |
| --- | --- |
| `jevops.hooks` | Optional consumer callbacks (`load_board`, `token_count`, …). Kernel never requires them. |
| `jevops.nca` | Cell store, tick/halt, inspect_python, mutate overlay, dispatch_tool |
| `jevops.walk` | Inner loop, compose dispatch, ptr CALL, nest/spawn, admit_step |
| `jevops.board` | Generic goal/subgoal/task grid seed, status overlay, mark_ready |
| `jevops.outer` | Outer JSON actions, `run_steps` / `route_next`, stall/stop |
| `jevops.oracle` | Candidate order, try_kind / apply_round / pack_eval |
| `jevops.pick` | Jev beam, leftover rank, shorter_bag, sample/filter records |
| `jevops.memory` | Success/failure/blacklist/research JSON memory, gap_report |
| `jevops.jev` | Choice/Score/Noul projectors, truncate_middle, FixtureClient |
| `jevops.kernel` | L0–L3 cache, CID, ARC/LRU, negative TTL, single-flight, context budget |
| `jevops.tape` | Neural tape (window, splice, mask, pop, byte trim) |
| `jevops.stack` | `ptr://` CALL/RETURN stack |
| `jevops.jsonld` | JSON-LD graph interface; DuckDB optional |
| `jevops.plan` | Goal / subgoal / task DAG + graph-of-thoughts |
| `jevops.graph` | Traverse, GraphRAG (JSON-LD first), milles message-pass |
| `jevops.skill_tree` | Hierarchical skill catalog |
| `jevops.rankers` | RF / Bayes-time / MCMC / SVD dispatch |
| `jevops.int_rankers` | Integer milles rankers |
| `jevops.more_rankers` | Markov / isotonic / AdaBoost / PageRank / contrastive |
| `jevops.temporal` | Hawkes / CRF / submodular / delayed bandit / tape conv |
| `jevops.tactics` | Lean tactic analysis plus explicit multi-armed-bandit action tactic |
| `jevops.autoencoder` | Canonical Lean IR, sparse trainable autoencoder, verifier-gated rewards |
| `jevops.autoencoder_training` | Cross-entropy/cosine training, LR schedule, canary/holdout protocol |
| `jevops.logic_ir` | Bounded propositional IR, K-map/Quine–McCluskey minimization, BDDs and invariant obligations |
| `jevops.logic_refactor` | Compiler-gated logic/arithmetic/structural reduction catalog and rotating sweeps |
| `jevops.program` | Closed IR compile/parse, work-ops execute (lake/board via hooks) |
| `jevops.repair` | Diagnose/heal grid, tape, stack, program_state |
| `jevops.tools` | TypeSafe tool catalog, MCP++ describe, subloops, KG |
| `jevops.harness` | Inner JevOps self-analysis + outer `llm_router` autoresearch gate |
| `jevops.proof_ca` | Proof-carrying typed ground-Horn graph cellular automaton |
| `jevops.proof_ca_demo` | Offline JSON trace and matched scheduling benchmark |
| `jevops.turing` | TM step/run + decision-transformer window |
| `jevops.tape_tools` | Tape editor CALLs (`port_tape_*`) |

## Arena measurement and score-aware search (opt-in)

For the stricter objective of reducing **both proof tokens and heartbeats**,
see the [dual-improvement and anti-reward-hacking plan](LEAN_TOKEN_HEARTBEAT_SAFETY_PLAN.md).
Its [2026-09-25 audit](papers/completion/lean_refactor_arena/evidence/goal-plan-audit-2026-09-25/README.md)
verifies default pytest-seal behavior and reviews upstream logic/hammer/tactician
reuse, while keeping aggregate trade-offs and remaining security gates explicit.
The [follow-up Strata support experiment](papers/completion/lean_refactor_arena/evidence/solver-support-strata-2026-09-25/README.md)
fixes silently skipped `simp only [...] at *` deletions. All six deletion
candidates failed fresh whole-proof checking (10 total native checks); no new
candidate or score gain was found, and the 185-token strict incumbent is unchanged.
That comparator was historical: a subsequent archive reconciliation recovered
the stronger 169-token incumbent. The [three-leaf reconstruction trial](papers/completion/lean_refactor_arena/evidence/subset-triple-strata-2026-09-25/README.md)
freshly checked it and rejected new 149/153-token grind proofs for added
`Classical.choice` and higher heartbeats. No improvement was promoted.
The [constructive normalization follow-up](papers/completion/lean_refactor_arena/evidence/subset-normalize-strata-2026-09-25/README.md)
then verified both 163/161-token drafts without axiom growth, but they used
30.43%/28.83% more raw heartbeats than the 169-token incumbent. All 16 screening
checks verified; no candidate qualified for confirmation. The incumbent is
retained, with 602 targeted tests passed and six explicit skips for this increment.
The [direct append-term experiment](papers/completion/lean_refactor_arena/evidence/subset-term-strata-2026-09-25/README.md)
adds an explicit aggregate-objective opt-in to the leaf pilot; strict-dual
remains the default. Both 181/178-token drafts verified, but used 1.62%/1.86%
more heartbeats than the 169-token incumbent and lost 2.067/1.657 local combined
score points. No confirmation or promotion occurred; 660 targeted tests passed,
six skipped.
The [tactic profiling diagnostic](ARENA_TACTIC_PROFILE.md) now runs through the
existing project-bound runtime. A [completed coarse Strata profile](papers/completion/lean_refactor_arena/evidence/tactic-profile-coarse-strata-2026-09-25/README.md)
found the shared simplification prefix at **56.39% of instrumented command
cost**, versus 4.94% for the `ite` case, consistently across three incumbent
profiles. These are diagnostic shares, not predicted savings or Arena scores.
The 169-token incumbent is unchanged; 315 offline tests passed with eight
skips, and three opt-in native tests passed. The earlier event-cap failure is
retained separately.
The [shared-prefix specialization trial](papers/completion/lean_refactor_arena/evidence/prefix-reference-strata-2026-09-25/README.md)
then confirmed a **174-token aggregate candidate**: five extra tokens versus
the 169-token incumbent, **21.49% fewer raw heartbeats**, and **+2.776 local
combined-score points**. All 30 screening/confirmation checks verified with
unchanged axioms; the complete trial used 42/48 reserved native checks.
The new opt-in `prefix-reference-v1` solver-pilot profile reuses bounded
parser-bound discovery and fresh aggregate selection. This is not a strict-dual
win, whole-corpus score or promotion; retain the 169-token shorter baseline.
Targeted regression: 334 offline tests passed / three skipped, plus two explicit
pinned-native tests passed. Legacy solver-feedback integration tests now
require opt-in instead of launching merely because Lean is installed.
The [simplifier-scope follow-up](papers/completion/lean_refactor_arena/evidence/simp-scope-strata-2026-09-25/README.md)
then confirmed **172 tokens and 7.70% fewer raw heartbeats** versus the 174-token
candidate, adding **+1.293 local combined-score points**. Removing only `at *`
kept all support lemmas and case proofs unchanged. All 34 native checks verified
with unchanged axioms; 607 targeted offline tests passed / three skipped.
The new `simp-prefix-scope` profile reuses the composition/leaf pilot. The
172-token aggregate candidate is still longer than the separate 169-token
shorter baseline; no strict-dual win over that baseline, corpus-wide score,
or production promotion is claimed.
The [joint append-tree follow-up](papers/completion/lean_refactor_arena/evidence/append-tree-strata-2026-09-25/README.md)
confirmed **172 → 170 tokens**, **3.61% fewer raw heartbeats**, and another
**+0.730 local combined-score points**. Deletion-only failed four checks;
deletion plus dependent `ite` repair passed all fresh confirmation checks,
without axiom growth. The [`simp-prefix-append-tree` profile](ARENA_APPEND_TREE.md)
reuses the same composition/leaf pilot. Total: 34 native checks (30 verified,
four rejected controls), 659 offline tests passed / three skipped. The
aggregate development candidate reached 170 tokens; the separate historical
169-token source was still shorter. No production promotion or corpus-wide score.
The [remaining-support trial](papers/completion/lean_refactor_arena/evidence/prefix-deletions-strata-2026-09-25/README.md)
then confirmed **170 → 168 tokens**, **11.87% fewer raw heartbeats**, and
**+1.661 local combined-score points**, by deleting one explicit `getVars`
simplifier entry while preserving all repaired case proofs. The opt-in
`simp-prefix-single-deletions` profile tests each entry from a bounded complete
support list. Two deletions verified, two failed; only the better valid draft
was freshly confirmed. All 18 confirmation checks passed with unchanged axioms;
42 total native checks and 716 offline passes / three skips. That
aggregate development candidate has **168 tokens**; the historical 169-token
source was not rechecked in this trial. No official score or promotion is claimed.
The [joint-deletion follow-up](papers/completion/lean_refactor_arena/evidence/prefix-joint-strata-2026-09-25/README.md)
confirmed a smaller **166-token aggregate candidate**, but with **1.56% more
raw heartbeats** than 168 tokens. The local combined gain is **+0.142 points**;
this is **not** a strict-dual improvement. Both remain on the Pareto frontier:
retain 168 tokens as the faster alternative. The `simp-prefix-drop-second`
profile reuses the existing bounded edit; all 30 native checks verified,
725 offline tests passed / three skipped, and the snapshot/audit passed.
Further full-copy trials need a storage plan: about 147 MB remains under the
unchanged 50 GB cap. No caches were deleted or production proof promoted.
The plan prioritizes dependency-aware deletion/repair and narrow solver replay,
with all-version proof checks and separate confirmation before promotion.
The [bounded selector](ARENA_PARETO_SELECTION.md) now supports
`--selection-objective strict-dual-v1`: strictly fewer tokens and lower
heartbeats in every version/order stratum, with a predeclared raw-unit noise
floor and fresh confirmation. The default Pareto and scalar router modes are
unchanged. Production promotion and stronger isolation remain roadmap items.
For the combined-score objective, opt in to `--selection-objective
aggregate-local-v1`: it permits token/heartbeat trade-offs, with exact normalized
deltas and fresh primary-pin controls in both branch orders. Every declared pin
must still verify without axiom growth. This is a **local score estimate**, not
an official Arena score; worker metric parity is unconfirmed. See the
[formula and confirmation rules](ARENA_PARETO_SELECTION.md#aggregate-local-score-opt-in).
The [frozen Physlib comparison](papers/completion/lean_refactor_arena/evidence/solver-aggregate-pilot-2026-09-24/README.md)
confirmed a saved five-token-longer specialization with about 8.63% lower raw
heartbeats: roughly +2.755 local combined-score percentage points, across 24
fresh native checks. This is one exposed task, not an official or corpus-wide score.
The same selector accepts `--repair-from-trial` to derive unverified drafts
from source-bound overapplication diagnostics. This narrow argument/goal-block
repair is not a general dependency analyzer; all generated drafts need fresh
checks. Long experiments can run from a read-only source bundle to avoid live
checkout edits invalidating their source identities; see the selector guide.

[Bounded draft compositions](ARENA_COMPOSITIONS.md) also accept historical
seeds and 19 existing portable rewrite rules, with explicit reference-token
accounting. Hash-bound LLM/hammer rule nominations can enter through an offline
proposal file; claimed verification or reward fields are rejected. This is
proposal generation, not live solver integration, training or proof authority.

[Premise ranking and injected providers](ARENA_PROVIDERS.md) add an indexed,
scope-bound lexical baseline and deterministic/offline/bounded-command proposal
adapters. Declared held-out aliases and dependents are excluded; external
responses cannot nominate arbitrary code or claim verification. Generated
four-field drafts feed the same fresh native selector. No live model or training
is enabled by default, and declaration inventories still require a trusted caller.

[Checked solver specialization](ARENA_SOLVER_SPECIALIZATION.md) adds opt-in
whole-source replay of solver suggestions and explicit-support deletions, plus
a bounded frontier that can retain longer intermediate proofs. Run the offline
three-arm control with `python -m jevops.arena_solver --demo`; its costs are
explicitly synthetic. `ArenaLocalRuntime.discover_solver()` uses an injected
native guard, while fresh all-pin strict-dual selection remains a separate gate.
Discovery never replaces the incumbent or claims an official Arena score.
`draft_policy="discovery-aggregate-v1"` can nominate a checked longer final
draft when its seed-normalized discovery score improves; it does not supply
confirmation evidence or change the default shortest-draft filter.
For a non-original seed, `draft_policy="discovery-reference-v1"` instead
normalizes both cost changes against the original source and its fresh raw
heartbeat observation from the seed check. It uses exact rational arithmetic,
adds no verifier calls, and abstains on a zero denominator. This primary-pin
nomination still requires fresh aggregate screening and confirmation against
both the original and incumbent; historical policy versions are unchanged.
The frozen `python -m jevops.arena_solver_pilot --problem NAME` command emits a
three-arm public-Arena experiment plan; native execution is explicitly opt-in,
serial, disk-capped, and includes fresh strict-dual confirmation for survivors.
Add `--comparison balanced-v1` for a frozen two-arm comparison of support-first
versus hint-aware state admission under the same limits. Both arms use the same
discovery-only cost nomination heuristic; neither bypasses fresh confirmation.
Use `--comparison aggregate-nomination-v1` to hold bounded search fixed and
compare dual-first versus aggregate nomination, with common aggregate screening
and fresh confirmation. An explicit `--incumbent` is freshly checked; gains
already achieved by it cannot be counted as new improvements. This profile is
plan-only unless explicitly executed from a validated frozen source copy.
The [matched Strata trial](papers/completion/lean_refactor_arena/evidence/solver-nomination-strata-2026-09-24/README.md)
used 18 native checks and produced no new nominee: a 197-token alternative to
the 185-token incumbent saved too few heartbeats to compensate for its size.
It also exposed rejected multiline tactic-span edits. The native solver now
uses bounded **Lean-parser source spans**, preserves the enclosing continuation,
and merges compatible per-goal `only` hints into one whole-proof replay proposal.
Older adapters without spans skip ambiguous multiline sites. This repair does
not change the historical trial or establish an additional Arena score gain.
See [span safety and limitations](ARENA_SOLVER_SPECIALIZATION.md#parser-bound-solver-edits).
The subsequent [fixed-candidate Strata confirmation](papers/completion/lean_refactor_arena/evidence/solver-reference-strata-2026-09-24/README.md)
passed all 30 fresh native checks: the 190-token merged replacement used about
11.84% fewer heartbeats than the 185-token incumbent and improved this problem's
matched-local combined score by 2.76779 points. It is also smaller/faster than
the original. This is not a discovery-policy ablation, corpus-wide score,
official leaderboard result or automatic promotion.

The first slice of the [Arena improvement plan](LEAN_REFACTOR_ARENA_IMPROVEMENT_PLAN.md)
adds a separate evaluator; the frozen `LRA/v1` proxy and default shortest-proof
router behavior are unchanged.

The opt-in [native application/materialization path](ARENA_APPLICATION_MATERIALIZATION.md)
now separates bounded search from final proof-source filtering. Lean checks
lemma application and every premise, extracts an explicit term, and independently
replays it before emitting shorter, still-unadmitted drafts. Headroom/small-span
ordering is selectable; baseline strategies and all-pin cost gates are unchanged.
The synthetic control is plan-only by default (add `--execute --max-processes 8`
for the two already-installed default pins; no downloads or models):

```bash
python papers/completion/lean_refactor_arena/tools/run_local_application_control.py
```

[Native typed premise features](ARENA_TYPED_PREMISES.md) are opt-in through
`NativePremiseExporter(include_signatures=True)` and
`discover_batch(retrieval="typed-head-v1")`. They prioritize raw conclusion
heads while retaining bounded lexical/generic fallback; native application and
all-pin admission remain mandatory. V1 inventories and default strategies stay
compatible. The existing pilot offers `--comparison application-retrieval` for
a matched, fixed-budget comparison, with no automatic promotion.

[Bounded backward construction](ARENA_BOUNDED_BACKWARD_SEARCH.md) adds opt-in
`span_order="matching-head-v1"` and `search="backward-v1"`. Lean can chain scoped
lemmas and solve conjunctions with state-restoring backtracking, separately
bounded primitive attempts, and independent script/term replay. The pilot's
`--comparison bounded-search` separates span ordering from construction in three
arms; process ceilings are matched, internal work is explicitly reported, and
all-version source/cost gates remain mandatory. No model or API is required.

[Scoped subgoal retrieval](ARENA_SUBGOAL_RETRIEVAL.md) extends that search with
`search="subgoal-v1"`: newly created goals can retrieve other lemmas from a bounded,
scope-filtered inventory, with explicit query traces and separate non-refundable
budgets. `--comparison subgoal-retrieval` compares fixed and dynamic pools before
separately increasing depth. Root ranking, legacy modes, and proof/cost admission
remain unchanged; no rewriting or live model is enabled.

[Reversible sibling discharge](ARENA_SUBGOAL_ORDERING.md) adds opt-in
`discharge_window=8`: try local hypotheses on a bounded set of pending goals
before expanding the first one. These attempts share the primitive budget;
failed downstream branches restore all assignments. Indexed paths must replay
from the original context before a shorter draft can be emitted. The frozen
pilot's `--comparison subgoal-ordering` changes only this ordering option.
The first real Core comparison produced no shorter drafts and increased counted
primitive work (304 → 374); the option remains disabled by default. See the
[recorded negative result](papers/completion/lean_refactor_arena/evidence/subgoal-ordering-pilot-2026-09-24/README.md).

[Conservative cycle detection](ARENA_CYCLE_GUARD.md) adds opt-in, branch-local
structural comparison of meta-free proposition/context states. It preserves
independent siblings, abstains on data goals or unresolved constraints, and
accounts for inspection separately. Successful searches still require native
script and term replay; pruning is not proof admission or a default policy.
Its [frozen Core trial](papers/completion/lean_refactor_arena/evidence/cycle-guard-pilot-2026-09-24/README.md)
found no shorter drafts or eligible repeats: 48/51 inspected keys contained raw
metavariables. Search traces were unchanged; this is a negative result, not an
Arena score improvement.

[Assignment-aware cycle keys](ARENA_ASSIGNED_CYCLE_GUARD.md) optionally follow
existing term/universe assignments with bounded traversal, without solving
constraints or weakening context identity. Unresolved/delayed assignments still
abstain. V6 traces separate dereferencing work from tactic attempts; native
replay remains mandatory. Use `cycle_key="assigned-v1"` with an enabled guard.
The [assignment-aware Core trial](papers/completion/lean_refactor_arena/evidence/assigned-cycle-pilot-2026-09-24/README.md)
raised key eligibility from 3/51 to 17/51 but found no repeats or shorter drafts.
The other 34 inspections first hit unresolved goal terms; search traces were
unchanged. This added inspection work, not an Arena improvement.

[Proposition-only discharge](ARENA_PROPOSITION_DISCHARGE.md) adds the opt-in
`discharge_filter="propositions-v1"`: Lean classifies goal sorts without retaining
inspection-induced assignments, then skips data/unknown goals for early
hypothesis discharge. Skips remain pending obligations. Inspections have their
own non-refundable budget and trace; an `observe-all-v1` control isolates the
filter from observation overhead. Use `--comparison proposition-discharge` for
the frozen three-arm protocol; proof admission remains unchanged.
The [first filter trial](papers/completion/lean_refactor_arena/evidence/proposition-discharge-pilot-2026-09-24/README.md)
found no shorter drafts: it reduced primitive work versus unrestricted discharge
but added inspections and still used more primitives than baseline. Defaults
remain unchanged.

```bash
python -m jevops.arena --calibrate
python -m jevops.arena_demo
python -m pytest -q tests/test_arena.py tests/test_router_tuning.py
```

Calibration matches all **15 published reference token counts**, using the
known statement boundary, qualified names, and operator tokens. It reports all
**36 required version checks as unmeasured**: this command does not run Lean.
Worker-level token/heartbeat parity is still unconfirmed. The old local token
counter remains available for reproducing historical reports.

Recounting the saved `CallElimCorrect.substOldPostSubset` artifact gives
**313 → 237** with the new counter, versus its preserved **482 → 391** historical
local counts. This is a source-length observation, not a fresh compilation,
heartbeat measurement, or official combined score.

The demo runs the existing router with an injected deterministic proposer and
mock verifier. Its synthetic heartbeat observations make a longer proof win over
a shorter, costlier proof. It calls no model and performs no Lean compilation;
its score is not a benchmark result.

For programmatic use, inject an `ArenaEvaluator` into `RouterTuningLoop` with
`RouterTuningConfig(selection_objective="arena-v1", train=False)`, and supply
the desired `router_generate` callback. This mode rejects a legacy `compile_fn`.
`ArenaContext` binds the original declaration, listed version pins, per-version
dependency-manifest hashes, verifier identity/options, axiom policy, and metric
scope. The verifier receives a `VerificationRequest` and returns a typed
`VersionReceipt`; it must actually check the original target/type in the correct
environment, avoid circular access to the target, and supply the axiom audit and
heartbeat measurement. Merely setting `theorem_ok` in a policy response cannot
admit a candidate. Hashes bind receipts but do not authenticate a dishonest
injected verifier. The optional local native adapter below supplies these checks;
it is not the organizer's worker or the frozen Lake admission path.

The evaluator checks receipt identities, process/type attestations and axiom
reports, with integer call reservations and entry/byte-bounded terminal-result
caching. Transient errors are not cached as rejection; reuse is not a new call.
`MEASURED` means all needed observations are present, `REJECTED` means local
intake or default verification failed, and `INCOMPLETE` leaves the score null
for missing checks/heartbeats, timeouts, infrastructure errors, or exhausted
budgets. Failed non-default version checks lower compatibility; missing checks
never silently become 100% compatibility. Scores preserve negative reductions
and mirror the pinned public leaderboard's rounding, including aggregate rounding.

The existing router keeps the checked incumbent and compares measured
length/heartbeat/compatibility scores, with compatibility breaking equal-score
ties. Legacy body-token and reconstruction diagnostics stay separate; model
training/promotion is disabled in this initial mode. Verifier-call accounting
is local and single-owner; adapter/API/currency accounting, OS isolation, full
worker parity and the real 36-check baseline remain follow-up work. Reports
always leave `official_score` null.

### Opt-in native Lean checks

```bash
python -m jevops.arena_lean --readiness
python -m jevops.arena_lean --smoke --tag v4.26.0 --max-processes 2
JEVOPS_ARENA_NATIVE_TESTS=1 python -m pytest -q --test-seal=off tests/test_arena_lean.py
```

The smoke command really runs the explicitly pinned, already installed Lean;
it does not call a model or install anything. It checks a small non-Arena theorem,
calibrates the reference using the same native heartbeat method, and checks a
shorter candidate. Raw heartbeat counts, type/axiom checks, source/context
identities, and wall time are retained in receipts. The local combined score is
**not an Arena score**; official worker metric parity remains unconfirmed.

For corpus baselines, provide explicit prepared project bindings and a nonzero
process budget. Projects are read-only: no checkout, splice, build, or download.
The adapter supports file-less Putnam rows using the frozen header, exact
Mathlib commit and checked Lake dependency lockfile. `--state-root /path/to/track1-lake`
inventories an existing harness cache without silently changing its revisions;
`--output /path/to/new-report.json` preserves a report without overwriting one.
Each branch starts before the original theorem, rejects an already available
target, and compares the actual elaborated theorem type with the reference.
Dependency applicability is checked before cache reuse and after native work.
Use `NativeLeanVerifier.calibrate()` then `.evaluator()` to connect this path to
the existing score-aware router; uncalibrated native selection is refused.

The default remains **trusted local execution, not an OS sandbox**. An explicit
`--isolation docker --docker-socket /absolute/local/socket --docker-image-id sha256:...`
now selects a fail-closed rootless Docker profile: no network, read-only inputs,
bounded CPU/memory/PIDs and scratch. It requires an existing pinned local image;
there are no automatic pulls or privileged/host fallbacks. Toolchains, imports,
the daemon and stable dependency files remain trusted. Candidate and checker
still share a Lean process: host isolation does not establish report honesty or
provide separate proof replay. Missing capabilities remain non-success outcomes.
See [setup, live canaries and limitations](ARENA_NATIVE_VERIFIER.md#optional-rootless-docker-execution).
An additional [isolated proof-data replay diagnostic](ARENA_TERM_REPLAY.md)
exports a bounded structural term and kernel-checks it in a fresh process against
the frozen challenge. It never executes candidate source in the checker, but
does not yet establish source/export correspondence or honest cost measurements;
its result cannot promote or train a candidate.
Its optional `--cold` mode measures each arm in a fresh producer process,
with a separately reserved proof-data check and fixed repeated comparison.
These [cold observations](ARENA_TERM_REPLAY.md#cold-single-branch-observations--partial-ticket-1c)
remove cross-branch process warmth, not the remaining source/counter trust gaps;
they cannot authorize promotion or a benchmark score.
The opt-in [explicit-term structural gate](ARENA_TERM_REPLAY.md#explicit-term-structural-gate--partial-tickets-1b1d)
(`--explicit-source`) rejects unsupported source and mismatched proof exports
without executing candidate tactics in the checker. It covers a small explicit
term grammar, not imported-syntax auditing or source/cost execution attestation;
automatic promotion remains disabled.
The optional [checked export-size guard](ARENA_TERM_REPLAY.md#checked-export-size-guard--partial-ticket-1d)
(`--cold --export-size-guard`) rejects proof/type DAG or expanded-tree growth
even when source tokens and reported heartbeats decrease. Sizes are computed
by the parent after each fresh proof-data check; this still does not authenticate
source execution, counter honesty or unmeasured work.
The [post-preparation native baseline](papers/completion/lean_refactor_arena/evidence/native-baseline-prepared-2026-09-22.json)
verified 17 of 36 required warm-up version checks; 19 remained unavailable in
that run (up from 12 verified in the earlier recorded baseline).
These are unchanged reference proofs, not an optimization gain or Arena score.
The [subsequent Cslib v4.33-rc2 baseline](papers/completion/lean_refactor_arena/evidence/native-baseline-cslib-rc2-2026-09-22.json)
verified its three targeted checks. Its restricted manifest omitted the other
33 rows; this is not lost coverage. Together these two saved runs contain
20 distinct verified problem/version checks, with 16 still unverified; this
historical union is not a fresh all-environment revalidation.

### Controlled refactoring trials

`python -m jevops.arena_trial --plan --problem CallElimCorrect.substOldPostSubset`
prints a fixed experiment schedule without running Lean. Supply explicit cached
projects, heuristic strategies or a historical seed, and `--run --max-calls N`
to measure candidates against unchanged controls in both proof-branch orders.
Use `--candidate draft.json` for a new, explicitly labeled unverified draft;
it is not treated as a historical successful seed.
Receipt caches are disabled, missing versions remain visible, and repeated
measurements do not silently become independent proofs via cache reuse. There
are no model calls, automatic promotions or Arena-score claims. See
[commands, protocol and limits](ARENA_CONTROLLED_TRIALS.md).
The [recorded diagnostic-guided Core repair](papers/completion/lean_refactor_arena/evidence/native-controlled-core-repair-2026-09-22.json)
passed 24 controlled checks across all three required versions: 224 → 216 tokens
and approximately 38–42% fewer raw heartbeats than matched controls. This is one
manual warm-up refactor, not an official Arena score or a trained-policy result.
The [fresh strict-dual confirmation](papers/completion/lean_refactor_arena/evidence/native-strict-dual-core-2026-09-23.json)
subsequently passed all 48 screening/confirmation checks from a fixed runtime
bundle, with both costs lower in every version/order stratum. The diagnostic
repair helper reproduces the same source as a new unverified draft; this is not
an additional task discovery. See the [measurements and provenance](ARENA_PARETO_SELECTION.md#clean-core-confirmation-and-repair-follow-up-2026-09-23).

### Bounded environment preparation

`jevops.arena_prepare` is an opt-in Linux preparation runner with a fixed-size
FUSE filesystem, read-only shared inputs, and one Docker build container at a
time. The authorized 50 GB allowance includes a 49.8 GB build image plus setup
headroom; downloads require `--allow-downloads`. Build success never substitutes
for the native proof checks. See [setup, recovery and limits](ARENA_PREPARATION.md).
Core tests do not require Docker, FUSE, network access or Lean installations.

Small compiled import trees can now be copied out of owner-only FUSE storage
with `arena_prepare --stage-imports`. Copies consume existing setup headroom,
not another disk allowance. The verifier binds the manifest hash and rechecks
original/copy bytes before use; its non-root/read-only policy is unchanged.
Use `--plan-imports` with the same import directories and byte allowance first:
it reports metadata-only feasibility without hashing, copying or reserving bytes.
Oversized trees fail closed; a fitting plan is not a validated import manifest.
See [the command, binding interface and tested limits](ARENA_PREPARATION.md#read-only-import-staging-partial-phase-1a).

## Skills

Grok skills live in `skills/` (canonical). LRA keeps thin `lra-*` redirects.

| Skill | Module |
| --- | --- |
| `jevops-hooks` | `jevops.hooks` |
| `jevops-kernel` | `jevops.kernel` |
| `jevops-nca` | `jevops.nca` |
| `jevops-tape` | `jevops.tape` / `tape_tools` |
| `jevops-stack` | `jevops.stack` |
| `jevops-skill-tree` | `jevops.skill_tree` |
| `jevops-walk` / `jevops-compose` | `jevops.walk` |
| `jevops-intent` | `jevops.jev` / `pick` / `walk` |
| `jevops-pick` | `jevops.pick` |
| `jevops-jev` / `jevops-redact` | `jevops.jev` |
| `jevops-oracle` | `jevops.oracle` |
| `jevops-outer` | `jevops.outer` |
| `jevops-memory` | `jevops.memory` |
| `jevops-repair` / `jevops-indent` | `jevops.repair` |
| `jevops-program` | `jevops.program` |
| `jevops-tools` | `jevops.tools` |
| `jevops-board` | `jevops.board` |
| `jevops-jsonld` | `jevops.jsonld` |
| `jevops-random-forest` / `jevops-bayes-time` / `jevops-mcmc` / `jevops-svd` / `jevops-ridge` / `jevops-thompson` | `jevops.rankers` |
| `jevops-int-rankers` / `jevops-pca` | `jevops.int_rankers` |
| `jevops-more-rankers` | `jevops.more_rankers` |
| `jevops-mask` / `jevops-mca` / `jevops-spans` | `jevops.mask` |
| `jevops-search` / `jevops-fills` | `jevops.search` / `jevops.mask` |
| `jevops-ast-rewrite` | `jevops.nca` |
| `jevops-autoencoder` | `jevops.autoencoder` |
| `jevops-graph` | `jevops.graph` |
| `jevops-temporal` | `jevops.temporal` |
| `jevops-turing` | `jevops.turing` / `tape` / `tape_tools` |
| `jevops-plan` | `jevops.plan` |

## Consumers

See [Logic reductions](LOGIC_REDUCTIONS.md) for the reduction catalog, limits,
proof obligations, and integration with router/autoencoder training.

Lean Refactor Arena harness re-exports these as `nca_kernel`, `nca_plan`, `typesafe_nca` cell helpers, etc.
Set `JEVOPS_CAS_DIR` for L2 CAS (LRA sets it to `evidence/canaries/nca-cas`).

Register implementation hooks instead of importing paper modules from the kernel:

```python
from jevops import hooks
hooks.register("load_board", my_board_loader)
hooks.register("token_count", my_token_count)
```

If hooks are missing, the kernel `try_import`s consumer modules that happen to be on `PYTHONPATH` (LRA harness). Missing hooks fail closed.

## Dependency boundary and deprecation

This checkout has no Git submodule entry and does not require the separate
Endomorphosis `ipfs_accelerate` or `ipfs_datasets` repositories for its core
runtime. The small interfaces JevOps actually uses are now in-tree:

* `jevops.typesafe_inference` is the stdlib-only structured TypeSafe client;
* `jevops.llm_router` supplies deterministic offline, Codex CLI,
  OpenAI-compatible HTTP and local Leanstral routes;
* local JSON-LD, SQLite, and symbolic fallbacks remain the normal graph and
  receipt paths.

The old external repositories are compatibility inputs, not core
dependencies. `JEVOPS_USE_EXTERNAL_ROUTER=1` selects the deprecated
`ipfs_accelerate_py.llm_router`; `JEVOPS_USE_EXTERNAL_DEPS=1` enables the
deprecated optional datasets/accelerator adapters. Those paths emit
`DeprecationWarning`, are never silent proof authorities, and can be removed
after downstream consumers migrate. DuckDB, NumPy, and Lean/Lake remain
optional adapters/toolchains; they are not copied into this Python package.

The [Leanstral migration guide](LEANSTRAL_INTEGRATION.md) restores the original
Arena warm-up client without an accelerator checkout. `leanstral_local`
(`leanstral` alias) talks only to an already running docker0/loopback server;
it never starts a GPU process or falls back to another model. The hosted
Mistral adapter remains separate. Run the complete fixture-only protocol with:

```bash
python papers/completion/lean_refactor_arena/harness/run_warmup.py --offline-self-check
```

The [refactoring prompt guide](REFACTOR_PROMPTS.md) adds opt-in `minimize`,
`repair`, `contrastive`, `performance`, `portable`, `coupled-repair` and `replan`
templates using explicit previous-round trials and checked archive inputs.
`--provider muse` or `--provider leanstral_local` renders structured messages
offline for either existing adapter; no model request is made. The new templates
combine native diagnostics, successful contrasts and exhausted-catalog coverage.
Preview them offline with
`python -m jevops.refactor_prompts --problem Core.InitsUpdatesComm --template repair`,
or pass `--prompt-template` and repeatable `--prompt-history` options to the
warm-up harness. Historical successes, errors, costs and version coverage are
source/context-bound hints, never new proof evidence; the legacy prompt and
existing admission checks remain unchanged by default.
The [live template pilot](REFACTOR_PROMPT_EXPERIMENTS.md) records the first
eight-call comparison, including empty responses and rejected drafts; it does
not establish a model-quality or Arena-score improvement.
The [message-role/contract follow-up](REFACTOR_CONTRACT_EXPERIMENT.md) fixes
multiline tactic layout and compares four matched prompt treatments, with
separate reviewed, fail-fast native validity checks.
The [output-budget experiment](REFACTOR_OUTPUT_BUDGET_EXPERIMENT.md) separately
tests descriptive JSON instructions and a larger generation allowance.
The [stable-snapshot local-edit pilot](REFACTOR_LOCAL_EDIT_EXPERIMENT.md) compares
whole-proof output with source-bound deletions using the existing proof slicer.
The [deletion-order experiment](REFACTOR_DELETION_ORDER_EXPERIMENT.md) tests
response-contract placement and deletion-choice order without reordering Lean tactics.
The [numbered edit-ID experiment](REFACTOR_DELETION_ID_EXPERIMENT.md) compares
source-bound catalog selections with line endpoints, keeping the contract last.
The [rejection-feedback experiment](REFACTOR_DELETION_FEEDBACK_EXPERIMENT.md)
tests bound native diagnostics as historical hints, without pruning edits or reusing proofs.
The [deterministic deletion-catalog screen](REFACTOR_DELETION_CATALOG_SWEEP.md)
checked all 64 available edits without model calls: none passed the first Lean
version, while all three reference controls passed. Broader edit actions are
needed before further selection-only prompt trials on this task.

## Two-level autoresearch loop

For the persistent Lean Refactor Arena watcher with real autoencoder training,
sandboxed Python-edit experiments, frozen native verification, and managed
generation deployment, see [Arena improvement watcher](IMPROVEMENT_WATCHER.md).
It preserves prepared caches and never overwrites the working checkout.

`jevops.harness.JevOpsHarness` runs a bounded inner/outer loop. The inner
iteration analyzes the JevOps source tree and updates AutoResearch memory; the
outer iteration calls the in-tree `jevops.llm_router.generate_text` facade for
a closed JSON action. `update_code` proposals use exact `old`/`new` text, are
evaluated in a temporary repository copy, and are applied only when the
injected evaluator improves (`score` is higher-is-better and `ok` must be
true).

```python
from jevops.harness import JevOpsHarness

harness = JevOpsHarness(
    root="/path/to/JevOps",
    evaluate_fn=lambda root: {"ok": True, "score": run_my_harness(root)},
)
receipt = harness.run(iterations=4)
```

The default is fully offline and deterministic:

```bash
python -m jevops.harness --iterations 4
```

For a real model, select an in-tree provider explicitly. The Codex CLI route
does not require the accelerator checkout:

For a bounded command-line run:

```bash
python -m jevops.harness --iterations 4 \
  --provider codex_cli --model gpt-5.6-luna --reasoning-effort high --strict-router
```

For a continuously supervised run, use `--continuous`. Each cycle performs
the inner self-analysis, asks the configured router for one closed action, and
persists memory plus a JSONL receipt. `--strict-router` prevents silent
cross-provider fallback; `update_code` is still applied only after the
isolated evaluator improves.

```bash
python -m jevops.harness --continuous --interval 60 \
  --provider codex_cli --model gpt-5.6-luna \
  --reasoning-effort high --strict-router
```

The TypeSafe provider is a structured System One evaluator, not a free-form
text generator. Keep its credential in `TYPESAFE_API_KEY` when TypeSafe gates
are used. Existing consumers that still require the external route may set
`JEVOPS_USE_EXTERNAL_ROUTER=1` and `JEVOPS_IPFS_ACCELERATE_PATH`, but that
compatibility path is deprecated.

### Router-guided proof tuning

`jevops.router_tuning.RouterTuningLoop` is the proof-specific router loop. It
asks the configured `llm_router` for bounded IR/tactic suggestions, expands
allowlisted local tactic families, compiles every candidate once, and trains
the Lean IR autoencoder only from the verified winner. The default route is
`provider="codex_cli"`, `model_name="gpt-5.6-luna"`, and strict
cross-provider fallback is off. The router is advisory; Lean/Lake remains the
admission authority and verified proof-body token count is the primary search
key. Strict mode also checks `llm_router`'s effective provider/model trace and
fails closed on a silent fallback; each round records that route attestation.
Training receipts distinguish the actual autoencoder `loss` from the verified
candidate's `candidate_target_loss`, so a perfect target match cannot masquerade
as a perfect model prediction. Results also expose `model_body_tokens_after`
separately from the verified-search `best_body_tokens`.

The search performs two bounded composition passes. The first crossovers the
current round's verified teachers; when that pool matches or improves the
previous elite, a second `max_elite_composed_candidates` pass composes the new
router/hammer/local/model teachers with older verified teachers. Derived
composition and IR-crossover rows are excluded as parents in the second pass,
and every candidate remains compiler/Lake-gated with parent provenance.

```python
from jevops.router_tuning import RouterTuningConfig, tune_autoencoder_with_router

result = tune_autoencoder_with_router(
    memory,
    theorem_source,
    problem="my-theorem",
    compile_fn=lake_compile,
    config=RouterTuningConfig(rounds=3, model_name="gpt-5.6-luna"),
)
```

For a standalone file, the bounded CLI is:

```bash
python -m jevops.router_tuning theorem.lean --lake \
  --provider codex_cli --model gpt-5.6-luna --rounds 3
```

The router-specific offline tests are `pytest -q tests/test_router_tuning.py`;
they inject a fixture router and never require router credentials.

## Lean IR autoencoder training

The autoencoder has two separate contracts:

* `encode_lean_ir` / `decode_lean_ir` use a deterministic, argument-preserving
  Lean IR (`jevops-lean-ir/v2`) and reject admitting or command-smuggling text.
* `train_autoencoder` trains a JSON-safe sparse model with teacher-forced
  operation cross-entropy, cosine-aware latent updates, gradient clipping,
  warmup/cosine/plateau learning-rate control, NCA auxiliary feedback, and
  bounded reward signals.

Lake/LRA remains the hard proof authority. TypeSafe/JeV can rank candidates or
provide soft fuzzy theorem-plausibility signals, but an unverified candidate
cannot enter the verified codebook. `minimality_score` rewards shorter
candidate equations only after semantic/proof gating. Training creates disjoint `train`, `validation`, `canary`, and
`holdout` assignments from a content-addressed manifest. The canary is a
regression gate, not an epoch-selection target; the holdout is not evaluated
until `evaluate_frozen_holdout` is called explicitly.

```python
from jevops.autoencoder import (
    AutoencoderConfig,
    evaluate_frozen_holdout,
    train_autoencoder,
)

config = AutoencoderConfig(seed=17, validation_fraction=0.1,
                           canary_fraction=0.1, holdout_fraction=0.1)
report = train_autoencoder(records, config=config, epochs=3,
                           compile_fn=lake_compile)
# Seal report["state"] and report["manifest"] before reading the holdout.
holdout = evaluate_frozen_holdout(report["state"], records,
                                  manifest=report["manifest"])
```

The implementation is dependency-free; a consumer can replace the sparse
backend with a vectorized/Torch trainer while retaining the same state,
metric, verifier, and holdout contracts.
For corpus-scale ingestion, `train_autoencoder_stream` accepts a
split-aware factory and never requests the `holdout` split during training.
Pass the training `memory` (or evaluator `nca_memory`) to use NCA cell energy,
neighborhood, residual-help, and historical verifier feedback as a bounded
auxiliary signal. `typesafe_fuzzy_prove` uses typed Choice/Score/Noul
questions as a fuzzy advisor; its result is always marked unverified and must
be followed by Lake compilation.
Disjoint workers can call `merge_model_states` to combine bounded sparse
checkpoints without gathering the corpus or retaining source text centrally.
For the integrated path, `refactor_smallest(...)` composes TypeSafe fuzzy
ranking, NCA feedback, Lake admission, and minimality selection in one call.
The offline three-round regression is `pytest -q tests/test_autoencoder_rounds.py`;
it invokes the installed Lean executable and compares against
`tests/fixtures/autoencoder_score_baseline.json`. That score is a frozen local
training proxy, not an official Lean Refactor Arena leaderboard result.
The same test also runs four deliberately compressible theorems through three
training rounds. Its shortest-proof proxy counts verified proof-body tokens,
keeps the pre-shrink result in
`tests/fixtures/autoencoder_smallest_baseline.json`, and requires every
shortening to pass Lean before it can win. The current local proxy is
`0.7797619047619048` versus the frozen pre-shrink `0.125`; neither is an
official Arena score.

For an isolated check of **learned** shortening rather than search success, run:

```bash
python -m jevops.training_probe --output /tmp/jevops-training-probe-new.json
```

This trains a fresh model on four compiler-checked synthetic deletion pairs,
then evaluates its actual rendered predictions on two held-out development
fixtures, a live-binding negative control, and eight randomized dependency
fixtures. It never uses arena data or production memory. The receipt includes
CE/cosine, compiler outcomes, the checkpoint, and separate **raw** and
dependency-guarded predictions. The raw model still deletes necessary bindings;
the conservative guard restores prerequisites or suppresses uncertain edits.
That is static protection, not learned dependency reasoning or evidence of
arena generalization. That is the default legacy experiment. To train the
opt-in binding keep/delete head on a balanced curriculum, run:

```bash
python -m jevops.training_probe --curriculum balanced --train-binding-policy \
  --output /tmp/jevops-binding-probe-new.json
```

This learns binary-classifier weights over **symbolic source dependency
features**. It reports binding BCE separately from sequence CE/cosine, along
with raw-head, guarded and old-decoder ablations. On 11 development fixtures,
the raw head produced four shorter, compiler-valid proofs without guard
restoration; the same-weights old decoder shortened none. Unsupported proof
structure is preserved, not compressed. That checkpoint's arena search tied
392 tokens; it did not improve the previous best and is not promoted. The router
can opt in with `RouterTuningConfig(train_binding_policy=True)` or
`--train-binding-policy`; raw proposals still require Lean admission. Canary
checks also reject binding-loss, verification and metric-coverage regressions.
See [validation details](LOGIC_REDUCTIONS.md).

For the expanded 33-family reduction catalog, bounded equality saturation,
Houdini invariant inference, proof slicing and strict axiom-audit mode, see
[kernel/refactoring research and implementation](KERNEL_REFACTORING_RESEARCH.md).
The report distinguishes implemented algorithms, optional Lean/Mathlib solver
proposals and remaining typed-expression/large-scale research work.

The opt-in learned span editor can also replace tactics and copy local names,
using verified shorter proofs as training targets. It is integrated through
`--train-rewrite-policy` and has a separate, isolated distillation runner.
Real model-only arena evaluation shortened 482→481 tokens and a historical
392-token seed→391, matching the local deterministic best. The original-input
CE gate failed, so the checkpoint is not promoted. See
[rewrite learning, research and reproducible evidence](REWRITE_DISTILLATION.md)
for ablations, finite GF(2) invariant mining and the limits of the small curriculum.

The [certified-refactoring follow-up](CERTIFIED_REFACTORING.md) adds balanced
solver-list reduction, application/eta edits and exact linear-invariant
certificates. An opt-in frozen-reconstruction edit head now passes both known
arena metric gates at the same 481/391 token counts. It also composes learned
edits on new branch layouts; no new high score or production promotion is claimed.

[Solver feedback and trajectory learning](SOLVER_TRAJECTORIES.md) adds opt-in
position-bound compiler suggestions and compiler-verified intermediate-step
training. Use `--solver-feedback --kernel-only` in the router, or
`--solver-feedback --trajectory-training --freeze-reconstruction-heads` in the
isolated distillation runner. Step CE/cosine coverage is tracked separately from
endpoint reconstruction and raw compiled predictions.

[Proof-cost-aware compression](KERNEL_COMPRESSION_NEXT.md) adds bounded
constructive term search, difference-bound redundancy certificates and
`--cost-guard` teacher/prediction admission in the distillation runner. Use
`--constructive-curriculum --difference-curriculum --constructive-terms`
to train on their verified outputs. The router separately supports
`--constructive-terms`; its source-length search does not implicitly enable
the distillation cost guard.

The [structural autoencoder implementation plan](STRUCTURAL_AUTOENCODER_PLAN.md)
includes JeV-guided learning from lossy candidates. The opt-in
`LeanIRAutoencoder.train_jev_feedback` API now computes expected-utility gradients
for the sparse edit policy, with bound receipts and an optional reference KL
penalty. Its default weight is zero; it neither calls a provider nor admits
proofs. A distilled critic, replayable open-state encoding, NCA gradients and
automatic outer-loop wiring remain planned. Fuzzy feedback supplements CE/cosine and
cannot replace Lean verification; fixture tests are not arena benchmark claims.

[Native expression DAG storage](EXPR_DAG_CODEC.md) now provides a bounded lossless
codec for closed `Lean.Expr` structures, including binder annotations, universe
levels and scalar metadata. The theorem exporter checks exact round trips and
rechecks decoded proofs with Lean's kernel. This is a storage representation,
not proof shortening or a trained graph autoencoder; syntax-valued metadata and
open proof states are explicitly rejected.

The opt-in [structural training bridge](STRUCTURAL_TRAINING.md) recompiles paired
training endpoints, checks their declared types and non-growing proof DAG costs,
and feeds accepted shorter targets to sparse rewrite distillation. Enable it with
`--structural-pairs --environment-sha256 <manifest-hash>`; add `--cost-guard` to
check raw evaluation predictions too. DAGs are retained as artifacts, not yet
used as graph-model features. CE/cosine objectives remain in place.

A separate [source-DAG edit-head experiment](STRUCTURAL_FEATURES.md) now trains
a sparse readout over fixed graph-neighborhood features. It compares one-step
lexical/structural selectors and graph-weight ablations with independent Lean
checks. The small native control experiment improves validity, not total verified
token savings; this is not a trained graph autoencoder or an arena result.

The opt-in [proof-state observation exporter](PROOF_STATE_CAPTURE.md) now captures
native InfoTree before/after states with local contexts and reachable term/universe
metavariable assignments. Its conservative dependency analyzer groups coupled
goals, and a bounded training-only collector excludes evaluation sources. This
is diagnostic data, not a replayable state codec or successful training labels;
it leaves model weights, proof gates and default outer-loop behavior unchanged.

A separate [native closing-replay bridge](PROOF_REPLAY.md) regenerates those
contexts from source and checks proposed closing tactics. Only independently
whole-proof/type/axiom/cost-checked shorter outputs become edit-head teachers.
The opt-in [local premise provider](ARENA_PROVIDERS.md#local-premise-replay-opt-in)
connects scoped library retrieval to those captured closing spans. Run
`python -m jevops.arena_providers --help` for `--capture` offline draft generation;
the existing replay and all-version Arena gates remain mandatory. This is a
deterministic lexical proposal baseline, not a trained model or an Arena win.
The explicit [project-context adapter and fixed pilot](ARENA_PROVIDERS.md#arena-project-context-and-controlled-comparison)
reuse prepared Arena prefixes, including open namespaces/sections, with
source-relative spans and context-bound local replay. The pilot compares whole
and local premise drafts under the same screening cap, reports extra discovery
work separately, and never promotes candidates or calls a model automatically.
The [first real-project pilot](ARENA_LOCAL_PREMISE_PILOT.md) completed screening
but found no accepted refactors (0/2 whole-proof and 0/2 local drafts). It records
unsupported inner contexts and a local baseline axiom-audit discrepancy rather
than turning either into proof labels or claimed score improvements.
The [local-context repair](ARENA_LOCAL_CONTEXT_REPAIR.md) fixes opaque-have
encoding, reuses the whole-proof module audit, and rejects synthetic branch
headers as edit targets. The real-project capture now validates all 37 selected
observations (previously 3), and the selected inner span's baseline passes kernel
checking in both replays. Observation coverage and replay validity are not refactoring scores;
fresh whole-proof, all-pin and cost gates remain mandatory.
The opt-in [local tactic portfolio](ARENA_LOCAL_TACTIC_PORTFOLIO.md) rotates
captured goals and tactic families, including guarded library application with
local arguments. Use `--capture ... --local-strategy portfolio-v1 --max-templates 128`
with `jevops.arena_providers`; the old baseline remains the default. A frozen
`--comparison local-portfolio` pilot provides equal native-check ceilings without
relaxing proof admission or claiming that deterministic templates are trained.
Installed-Lean argument controls passed; the first matched Strata run remained
0/2 all-pin-valid for both strategies, with no measured benchmark gain.
The bounded training CLI retains CE/cosine, freezes reconstruction parameters,
and evaluates raw predictions after checkpoint freeze; it is not an arena score.
Its `--curriculum transfer` mode adds three teacher families and six cross-structure
holdouts, with explicit no-applicable-rule controls and retained cost/coverage
failures. A known local-`let` case has shorter text but a larger proof DAG, so the
strict transfer experiment currently fails its cost gate as intended.
The separate `--curriculum compound --max-compiles 128` protocol adds atomic
two-line alias rewrites and continuation-retaining let-deletion rules. It trains
only from fresh checked endpoints; rejected partial edits remain visible. The
inspected transfer failure is evaluated after freeze as a separate known regression,
not recycled into training or counted as a fresh holdout. The original failing
benchmark remains unchanged; neither protocol promotes checkpoints.
An opt-in `--router-refinement-rounds` bridge now lets the existing router propose
repairs and tactic/composition hypotheses from training-only replay failures and
expression-cost diagnostics. Batches share a fixed budget; only checked endpoints
become teachers, and evaluation never calls the router. An explicit provider/model
is required for CLI use. Native tests use labeled offline callbacks; no live-model
improvement or arena high score is claimed. See [the protocol and trust boundaries](PROOF_REPLAY.md).

Generate reports from saved receipts with code, not an LLM-written artifact:

```bash
python -m jevops.refactor_report --run /path/to/distillation.json \
  --arena /path/to/arena.json --expressions /path/to/metrics.json \
  --output-dir /path/to/new-report
```

Only `--run` and `--output-dir` are required. The deterministic generator writes
a short `summary.md`, full machine-readable `evidence.json`, a replayable
`checkpoint.json`, and input/output hashes in `provenance.json`. It validates
checkpoint/manifest hashes, rejects mixed checkpoints and existing output files,
and prints only artifact paths. Missing measurements stay unavailable and failed
gates stay failed. Reporting neither reruns Lean/training nor promotes a model;
its exit code indicates report generation, not benchmark success. Keep raw run
receipts as the source of truth; generated summaries should not be hand-edited.
Use `--archive-inputs` to retain exact raw receipts as deterministic gzip files
inside the report bundle. The generator also accepts these `.json.gz` inputs.

## Action bandits and the neurosymbolic CA

`jevops.tactics.multi_armed_bandit` is the action-level policy primitive. A
selection creates one pending pull; a later call supplies the measured reward
in `[0, 1]` (or a Boolean). The tactic stores Beta/UCB statistics under
`memory["nca"]["bandits"]`, mirrors the action and outcome into `ptr://cell`
and `ptr://skill` cells, and journals the transition. It never treats a
selection as a proof or code admission.

```python
from jevops.tactics import multi_armed_bandit

pick = multi_armed_bandit(memory, ["port_simp", "port_cases"], seed=7)
# After the lake/evaluator measures pick["selected_arm"]:
next_pick = multi_armed_bandit(memory, ["port_simp", "port_cases"], reward=0.9)
```

The existing `port_thompson` ranker remains a pipeline-order heuristic. Use
the action bandit when a loop needs a real select→measure→update lifecycle.
The current NCA is a useful substrate—canonical cells, energy diffusion,
board edges, tape/stack receipts, and symbolic gates—but it is not yet a full
cellular automaton: the next architectural step is a synchronous, typed local
transition rule that consumes a cell state plus bounded neighbor messages and
emits a validated state delta. Keep Lean/Lake and evaluator receipts as the
symbolic authority for those deltas; keep the outer router responsible only
for bounded proposals.

## Proof-carrying graph cellular automaton

The strict symbolic runtime is in `jevops.proof_ca`. It uses a declared finite
universe of ground atoms and immutable positive Horn rules. Rule cells have
typed premise and conclusion edges; conjunction is checked by exact premise
identity, not by votes, activation averages, or incoming-edge counts. A fact
can enter the accepted set only as a declared assumption, a checked local rule
derivation, or a context-matched verified external receipt.

Run the complete offline example and benchmark with:

```bash
python -m jevops.proof_ca_demo
```

The command emits a JSON proof trace, an injected mock-verifier receipt, and a
matched comparison of a deterministic queue, a centralized controller using
the same action interface, and the local fair scheduler. It makes no API calls
and reports measured synthetic work only; `actual_cost` is `null` because no
paid service is used.

The runtime keeps symbolic, policy, evidence, and operational state separate.
`JevPolicyAdapter` is dependency-injected and receives only a bounded local
snapshot. Its selected value, distribution, confidence, question version, and
model identity are retained as non-authoritative observations. The deterministic
baseline is explicitly labelled a fixture. A periodic FIFO service guarantees
that a defer/rejecting policy cannot permanently suppress an enabled rule in
an unbounded run. Messages, proposals, evidence IDs, reservations, and
checkpoints are idempotent.

Final statuses are precise: `VERIFIED_COMPLETE` means all required targets
have checked supporting evidence; `QUIESCENT_INCOMPLETE` means closure with an
unproved target; `BUDGET_EXHAUSTED` means an explicit integer resource limit
blocked more work; `ERROR` means a runtime invariant or required adapter failed.
An absent verifier, timeout, test result, cache hit, activation value, or
legacy `theorem_ok` field is not silently promoted to proof. The initial
language is intentionally finite, ground, positive, and single-process; it is
not arbitrary theorem proving, distributed execution, learned neural dynamics,
or a claim about the truth of its trusted assumptions.

The invariant argument and its assumptions are documented in
`PROOF_CARRYING_NCA.md`.

## Not in this package

Portable Lean folds, `lake env`, random canaries, Track 1/2, LRA `tasks.json`
board, and the implementation-specific inner TypeSafe lake walker remain
consumer/toolchain concerns. The TypeSafe HTTP DTO/client itself is now
available in `jevops.typesafe_inference`; it remains an optional network
service, not a proof authority.

## Lean Refactor Arena benchmark integration

The frozen 15-problem warm-up corpus and the executable harness are under
`papers/completion/lean_refactor_arena/`. The harness keeps statement-prefix
binding, tag-pinned Lake compilation, `sorryAx` rejection, retained failures,
and null official-score fields. The experimental
`harness/autoencoder_bridge.py` connects those records to the router-guided
text → Lean IR → text loop; it reports the verified search winner separately
from the model's own prediction and its cross-entropy/cosine diagnostics.

```bash
python papers/completion/lean_refactor_arena/harness/run_warmup.py --plan
python papers/completion/lean_refactor_arena/tools/verify_lra_batch.py --schedule
python papers/completion/lean_refactor_arena/harness/autoencoder_bridge.py --plan
```

The upstream Lean Refactor implementation is vendored under
`papers/completion/lean_refactor_arena/upstream/`. See its
`UPSTREAM_IMPORT.md` for the source commit, optional dependency boundary, and
the Mathlib submodule pointer. Core JevOps tests do not require the upstream
model stack or a Mathlib checkout.

The public Arena Space UI snapshot is vendored under
`papers/completion/lean_refactor_arena/space/`; its manifest records that the
separate official evaluation worker is not included. This is source
provenance, not a claim of a live Arena submission or score.

The currently public optimization fixture is the frozen 15-row warm-up. Check
its readiness and exact corpus digest with:

```bash
python papers/completion/lean_refactor_arena/tools/check_corpus.py
```

The checker accepts the future full JSONL with `--jsonl ... --require-full`
and fails closed until a larger official corpus is actually present.

These commands are unscored protocol checks. A full run requires the listed
source clones and every pinned toolchain/cache; missing infrastructure stays a
failure and never becomes a PATH-Lean or Arena-score fallback.

## Incremental test seals

Pytest uses `--test-seal=on` by default (`pytest.ini`); `reuse` remains an alias.
Seals combine filesystem stat fast paths,
raw/AST hashes, and dependency Merkle roots. Ordinary unmarked tests reuse
unchanged passing evidence. Opt out with `@pytest.mark.no_seal(reason="…")` or
`--test-seal=off`; `--test-seal=refresh` forces execution and refreshes evidence.
`--test-seal=status` reports sealed/stale/failing/unsealed without running test
bodies. The `seal_dependencies` fixture declares file, directory, and executable
inputs. Known native Lean checks and non-hermetic probes stay fresh. See
[TEST_SEALS.md](TEST_SEALS.md) for the dependency contract and commands.
