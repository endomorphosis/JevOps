# Shorter, cheaper Lean proofs without weakening the task

Initial plan: **2026-09-22**; latest current-state audit: **2026-09-25**.
This is the focused implementation
roadmap for reducing **both proof-source tokens and Lean heartbeats**, while
preserving the original theorem and resisting reward hacking. It supplements
the [Arena competition plan](LEAN_REFACTOR_ARENA_IMPROVEMENT_PLAN.md).
The strict promotion contract below takes precedence for this objective over
that plan's score-trading recommendations. It does **not** change the published
Arena score or existing router defaults. The first strict selection increment
is now implemented; see the follow-up below for its limits.

## Current decision brief — 2026-09-25

The requested deliverable is a comprehensive implementation/evaluation plan,
working pytest-seal behavior, and a source-based reuse assessment. It is **not**
a claim that all roadmap items below are implemented or that the current
trusted-local verifier is safe against arbitrary hostile Lean metaprograms.
The [current audit, commands and artifacts](papers/completion/lean_refactor_arena/evidence/goal-plan-audit-2026-09-25/README.md)
separates these claims. Historical dated results below remain historical.

### Keep the two optimization objectives distinct

**Baseline correction (follow-up on 2026-09-25):** the solver-only experiments
below used 185 tokens but overlooked the previously confirmed 169-token winner
from `native-subset-shared-target-2026-09-24`. Their stated within-experiment
comparisons remain historical, not evidence that 185 is the best known strict
incumbent. The [three-leaf reconstruction follow-up](papers/completion/lean_refactor_arena/evidence/subset-triple-strata-2026-09-25/README.md)
uses the 169-token source and entirely fresh controls. Historical winner
selection must be reconciled across experiment families, not just the latest
solver branch; saved receipts never replace fresh checking.

That follow-up finished with `NO_IMPROVEMENT` after 20 native checks. Its
149-token and 153-token grind reconstructions added `Classical.choice` and
cost about 28.10% / 41.87% more raw heartbeats than the fresh 169-token baseline.
The simplification-only draft left explicit `True` connectives unreduced.
The [constructive normalization experiment](papers/completion/lean_refactor_arena/evidence/subset-normalize-strata-2026-09-25/README.md)
implemented that follow-up with two fixed explicit simp sets. All 16 screening
checks verified; both 163/161-token drafts preserved the original axiom set,
but cost 30.43%/28.83% more raw heartbeats than the fresh 169-token incumbent.
Result: `NO_IMPROVEMENT`; zero confirmation checks, retries, or promotions.
The unchanged snapshot and consistent report are archived with 602 passed /
six skipped targeted tests. This resolves that specific normalization failure,
not the optimization objective. Neither the cost gate nor the axiom policy was
relaxed.

The [direct append-term follow-up](papers/completion/lean_refactor_arena/evidence/subset-term-strata-2026-09-25/README.md)
implemented two bounded term renderings. Static counting showed 181/178 tokens,
so the experiment explicitly froze the separate **aggregate-local** objective
before native work; the strict default/incumbent were not changed. All 16 checks
verified without axiom growth, but heartbeats rose 1.62%/1.86%, giving local
combined-score losses of about 2.067/1.657 percentage points versus 169 tokens.
No confirmation or promotion occurred. The archive audit passed; 660 targeted
tests passed with six skips. Direct terms alone did not help these two layouts.
The next [profiling increment](ARENA_TACTIC_PROFILE.md) is now implemented in
the existing project-bound runtime. The fine-resolution pilot stopped at its
256-event cap after four verified controls; its partial trace was not used.
A separate frozen [coarse-profile run](papers/completion/lean_refactor_arena/evidence/tactic-profile-coarse-strata-2026-09-25/README.md)
completed four fresh controls and six profiles. Across all three incumbent
repeats, the shared `simp [...] at *` prefix accounted for **56.39% of the
instrumented command**, while the `ite` case was about **4.94%**. Instrumented
counts were about 8.27% above uninstrumented controls; do not use these shares
as score metrics or forecast savings. The diagnostic proposed bounded
specialization/support minimization using native parser spans and whole-source
verification. At that stage the incumbent was unchanged; 315 offline tests passed / eight skipped,
plus three explicitly opt-in native tests passed.

The [shared-prefix follow-up](papers/completion/lean_refactor_arena/evidence/prefix-reference-strata-2026-09-25/README.md)
has now **confirmed** that intervention under the separate aggregate objective.
The existing solver pilot's opt-in `prefix-reference-v1` profile made ten
discovery checks, retaining the five-entry `simp only` specialization; all six
deletions failed. Thirty fresh screening/confirmation checks verified, with
unchanged axioms. The **174-token** candidate costs **21.49% fewer raw
heartbeats** than the 169-token incumbent, giving **+2.77627 local score points**.
Total trial use: 42/48 reserved checks, unchanged source snapshot, consistent
audit. Targeted regression: 334 offline passes / three skips, plus two explicit
native passes on the prepared Lean 4.26.0 pin (eight separate compiler calls).
The earlier ambient-toolchain failures remain recorded, not erased by opt-in
gating. This was no strict-dual/corpus-wide win or promotion: that trial kept
the **169-token strict** and **174-token aggregate** baselines distinct. It
proposed dependency-aware continuation repair or narrower hypothesis
simplification as the next fixed trial.

The subsequent [scope-narrowing trial](papers/completion/lean_refactor_arena/evidence/simp-scope-strata-2026-09-25/README.md)
implemented the latter hypothesis: goal-only versus explicit-introduced-hypothesis
plus goal, keeping support and following case proofs unchanged. All **34 native
checks verified**. The independently confirmed goal-only candidate has **172
tokens**, **7.70% fewer raw heartbeats** and **+1.29287 local combined-score
points** versus 174 tokens. Both drafts qualified in screening; only the
better 172-token source was independently confirmed. The separate 169-token
source was not rechecked and remains shorter. Baselines at that point were
**169-token strict** and **172-token aggregate**, without a strict-dual win over
169 or any production promotion. The snapshot/audit passed; **607 offline tests
passed / three skipped**. Dependency-aware support deletion and case repair
were the next unrun hypothesis.

The [joint append-tree trial](papers/completion/lean_refactor_arena/evidence/append-tree-strata-2026-09-25/README.md)
then tested that hypothesis through the existing composition/leaf pilot.
Removing `List.append_assoc` alone failed all four screening checks. Pairing
the deletion with a left-nested `ite` proof tree gave **170 tokens**, **3.61223%
fewer raw heartbeats**, and **+0.72983 local combined-score points** versus the
fresh 172-token incumbent. All 18 confirmation checks verified, with unchanged
axioms; 34 total native calls, 659 offline passes / three skips. The snapshot
and consistency audit passed. Development baselines then were **169-token
strict** and **170-token aggregate**; the shorter source was not rechecked, so
this was no strict-dual win over 169 or production promotion. Remaining support
minimization was still untested from that repaired source; broader/held-out and
worker-parity gates remain open.

The [remaining-support single-deletion trial](papers/completion/lean_refactor_arena/evidence/prefix-deletions-strata-2026-09-25/README.md)
subsequently confirmed **168 tokens**, **11.87453% fewer raw heartbeats** and
**+1.66129 local combined-score points** versus the freshly checked 170-token
source. Both `getVars` deletions qualified in screening; deleting
`Lambda.LExpr.LExpr.getVars` was cheaper and alone received confirmation.
The other two support deletions failed. All 18 confirmation checks verified,
with unchanged axioms; 42 total native calls, 716 offline passes / three skips.
That aggregate candidate has **168 tokens**. It is shorter than the
historical 169-token source, but that source was not freshly rechecked in this
trial. Strict-dual reanalysis applies only to the supplied 170-token comparator.
Joint removal of the two individually valid entries was still untested;
neither composability nor global minimality followed from that trial.

The [joint-deletion experiment](papers/completion/lean_refactor_arena/evidence/prefix-joint-strata-2026-09-25/README.md)
then confirmed composability but **not additive cost savings**: **166 tokens**,
**1.56265% more raw heartbeats** than the fresh 168-token comparator, and only
**+0.14247 local combined-score points**. This passes the explicitly frozen
aggregate objective but fails strict-dual in both phases. Preserve both
Pareto candidates: **166-token aggregate** and **168-token faster alternative**.
All 30 native checks verified with unchanged axioms; 725 offline passes / three
skips, unchanged snapshot and consistent audit. No production promotion.
About 147 MB remains under the 50 GB cap; a storage/reduced-snapshot plan is
needed before another full-copy experiment, without silently reducing reserves
or deleting caches. Broader/held-out and worker-parity gates remain open.

For **both shorter and cheaper**, use `strict-dual-v1`: every required pin must
verify, tokens must decrease, and raw heartbeats must improve beyond the frozen
range/noise margin against **both original and incumbent** in screening and
fresh confirmation. `aggregate-local-v1` is a separate, explicitly selected
trade-off objective; it does not satisfy the strict contract by itself.

The [historical Strata confirmation](papers/completion/lean_refactor_arena/evidence/solver-reference-strata-2026-09-24/README.md)
has 30 verified native checks: 222 → 190 tokens and about 21.42% fewer heartbeats
versus the original, but **185 → 190 tokens** versus the incumbent. Its
11.84% heartbeat saving over that incumbent is a confirmed local aggregate win,
**not a dual-cost win over its then-used incumbent**. Preserve that historical
185/190 comparison, but use the corrected current baselines above for new work.
Do not silently change baselines to make an edit appear successful. No
production promotion occurred.

The [follow-up support-minimization run](papers/completion/lean_refactor_arena/evidence/solver-support-strata-2026-09-25/README.md)
fixed an `at *` nomination omission, then used ten fresh native checks. All six
single/empty-support deletions failed whole-proof replay; no new candidate
qualified. The five-entry seed survived unchanged. Diagnostics point to
branch-local reconstruction (notably `ite` append grouping) as the next bounded
intervention. This is a neutral optimization result, not evidence of global
minimality; that run retained its then-used 185-token comparator.

### Implementation priorities and stop rules

| Priority | Concrete next work in existing JevOps modules | Gate / stop rule |
| --- | --- | --- |
| P0: immutable contract and safety | Keep `arena`/`arena_lean` identities, separate-checker/source correspondence, trusted tactic/import policy, cold measurement and environment-delta accounting on the critical path | Sections 5–6 and tickets 1a–1e remain release gates; no automatic promotion or adversarial source execution through the trusted-local path |
| P1: specialize then minimize | Extend `arena_solver`/`solver_feedback` from complete parser spans: minimize `simp only`/supported solver dependencies, replay whole proofs, retain longer intermediates separately | Existing span repair is implemented and has native controls. A hint or locally passing edit is never enough; stop on call/state/source caps, not when a model says done |
| P2: deletion with dependency repair | Use `proof_state`, slicing and composition to delete redundant local facts, then repair affected induction arguments/goal blocks | Refresh observations after edits; accept no stale offsets, missing premises or weakened target. Compare with deletion-only at equal verification budgets |
| P3: typed local lemma reuse | Extend `premise_search`/`arena_providers`/native applicability, with target-free per-pin inventories and bounded local replay | Accessible/type-correct premises and heldout exclusions; local success still requires whole-source verification. Keep failed/neutral arms in reports |
| P4: bounded equational optimization | Try directed, typed rewrites and sharing within the charged proof; later compare a bounded equality-saturation arm | Preserve side conditions, universes and scope; measure final Lean costs rather than an extraction heuristic; charge new helper work |
| P5: allocation and optional learning | Compare fixed round-robin with the existing bandit tactic; only then evaluate model-pinned reranking/distillation on unused families | One reward per unique verified observation, explicit failures/timeouts, fixed confirmation reserve; no training on final canaries or claims from fixture/model confidence |

P1–P4 may run as restricted development experiments while P0 proceeds, but
cannot bypass its production gates. An equation/definition-changing refactor
uses the separate equivalence/caller-check contract in section 1, not the
same-statement Arena proof-body protocol. Reserve provisioning separately,
retain the one-build-at-a-time/50 GB cap, and keep measurement serial.

The literature supports these mechanisms, not promised JevOps percentages:
compiler-style syntax/semantic passes and observation invalidation
([Limperg](https://leaning.in/2026/slides/limperg.pdf)); structure-aware reduction
([HDD](https://www.cs.ucdavis.edu/~su/publications/icse06-hdd.pdf)); accessible
premise retrieval ([LeanDojo](https://arxiv.org/abs/2306.15626)); explicit solver
replay ([Lean reference](https://lean-lang.org/doc/reference/latest/The--grind--tactic/Minimizing--grind--calls/));
bounded rewrite exploration ([egg](https://arxiv.org/abs/2004.03082)); and
resource allocation ([Hyperband](https://www.jmlr.org/papers/v18/16-558.html)).
These primary sources were rechecked for this audit. Adapting their methods
to dual-cost Lean refactoring is an engineering hypothesis, not a transferred
performance guarantee. Probe tactic availability on the actual frozen pins.

### Seals and upstream reuse: verified current behavior

`pytest.ini` and `conftest.py` already enable the local seal plugin; no new
dependency or default change was needed. On an immutable copy of current code,
default cold/warm runs gave **303 passed / 291 sealed for reuse**, then
**12 freshly passed / 291 reused**, with 32 skips each time. All 29 selected
native proof/cost cases remained unsealed. The 42 seal self-tests passed fresh;
a separate safety/provider suite passed 480 tests with 136 explicit skips,
zero reused, and 470 fresh passes sealed. These are targeted offline suites,
not a full repository or new native Lean result. Use `refresh` for fresh
regression evidence; do not combine `-p no:cacheprovider` with a claim that
seals were active. Native checks must remain fresh regardless of seal mode.

The reviewed `ipfs_datasets_py` modules still match local revision
`7f0d38572f92f5fc0cba7a5ddd4bef28523876f3`, with no changes in the inspected
paths. Reuse the **contracts**, not the whole dependency tree: deterministic
premise filtering, typed per-hole proposals, reconstruction hints, model-pinned
fallback, and bounded discovery coordination. Preserve our exact source/context
identity, reject wrong-hole results, reserve before work, and add cancellation
to single-flight waits. Six read-only identity probes confirmed why the
upstream raw-text/opaque-value normalization must not be used for authoritative
Lean cache keys. See the [reuse matrix](#upstream-logic-hammer-and-tactician-adaptation-decisions)
and [current source/probe evidence](papers/completion/lean_refactor_arena/evidence/goal-plan-audit-2026-09-25/upstream-review.json).
Hammer/tactician are ordinary tracked modules; the CEC Git submodules are not
required or evaluated here. No external package, live provider or copied
implementation was added in this audit.

### Scope of completion

The planning/seal/reuse deliverable is evidenced by the audit. Unclosed
source-execution/metric-authenticity gates, full-corpus coverage, robust
held-out gains, production promotion, and the definition-equivalence adapter
remain implementation work. A green pytest result, cache seal, source hash,
kernel-checked export or local score alone cannot close those gates.

## Historical implementation record and detailed roadmap

**Current execution policy:** ordinary pytest runs use `--test-seal=on` through
`pytest.ini`; `reuse` is a compatible alias. Native proof, sandbox and heartbeat
canaries must stay fresh even when seals are enabled. Section 11 specifies the
cache boundary. Dated audit commands below describe historical runs, not the
recommended default or evidence that the remaining roadmap is complete.

The immediate sequence is: (1) preserve the checked incumbent and frozen cost
contract; (2) close source/export and cold-measurement trust gaps; (3) extract
native, target-free premise inventories and compare the existing bounded
proposers at equal budgets; (4) expand dependency repair and narrow solver
replay; (5) evaluate optional learning only on separately frozen families.

Implementation follow-up: [the existing bounded selector](ARENA_PARETO_SELECTION.md)
now accepts `--selection-objective strict-dual-v1` and a precommitted
`--heartbeat-noise-floor-raw`. It requires both costs to decrease against the
original and incumbent, on every pin/order, in screening and fresh confirmation.
This implements the selection criterion, not production promotion, a new
sandbox, proof-DAG cost checks or independent single-branch measurement.
Follow-up validation: 390 focused tests passed, 100 explicitly skipped;
20 fresh native stdlib-control executions verified with an unchanged selector
and a confirmed strict-dual recommendation. See the
[commands, receipts and overlap caveat](ARENA_PARETO_SELECTION.md#strict-mode-verification-2026-09-22).
This is an integration control, not an Arena result.
The next implemented increment adds source-bundle isolation and a narrow diagnostic-guided
argument/goal-block repair through `--repair-from-trial`. It reconstructs the
known Core repair as an unverified draft. This is not general dependency
analysis or new held-out optimization evidence; see the selector guide.
The [2026-09-23 fixed-runtime Core confirmation](ARENA_PARETO_SELECTION.md#clean-core-confirmation-and-repair-follow-up-2026-09-23)
now supplies 48/48 VERIFIED checks: the manually seeded repair passed strict
screening and fresh confirmation on all three pins and both branch orders,
with 224 → 216 tokens and 37.89–42.40% lower raw heartbeats. This does not
establish broader search generalization, add new task coverage or change the
remaining isolation/promotion requirements.
The checkout also now includes a bounded composition proposer and historical
report consistency audit. Their results and limits are incorporated below;
the [composition pilot](ARENA_COMPOSITIONS.md) includes a valid, shorter draft
that was **not** a strict improvement over its incumbent. None of these local
recommendations certifies the still-unimplemented production security gates.
The subsequent [historical recovery](papers/completion/lean_refactor_arena/evidence/native-historical-confirm-2026-09-23/report.json)
confirmed a **185-token** proof against that problem's 213-token incumbent, with
about 10.8% fewer raw heartbeats. A [portable-edit follow-up](papers/completion/lean_refactor_arena/evidence/native-portable-pilot-2026-09-23/report.json)
rejected all three shorter drafts. The recovered proof, freshly rechecked in
each new context, is the next development baseline; it is not a new discovery.

Phase-1 follow-up: the [native adapter's opt-in rootless Docker profile](ARENA_NATIVE_VERIFIER.md#optional-rootless-docker-execution)
now isolates host access with read-only inputs, no network and bounded kernel
resources. Actual Lean/Docker canaries and a two-check native smoke were run.
This is **partial phase 1**: that adapter's source checker and candidate still
share a process. The separate replay/cold diagnostics described below do not yet
close source admission, authenticated measurement, environment-delta audit or
whole-run setup deadlines. These remain release blockers. Direct binds of the
prepared owner-only FUSE volume remain incompatible with the non-root worker.
[Small read-only import staging](ARENA_PREPARATION.md#read-only-import-staging-partial-phase-1a)
now passes a real FUSE/build/import canary within existing setup headroom, with
source/copy checks and unchanged worker restrictions. Large compiler/library
copies and full prepared-corpus isolated controls remain open; no fallback
weakens the gate.
The [subsequent real-project control and metadata preflight](ARENA_PREPARATION.md#real-project-control-and-staging-preflight-2026-09-23)
checked the original `Core.InitsUpdatesComm` on host-readable v4.26.0 in the
isolated worker. The prepared v4.27.0/v4.29.1 import trees exceed the existing
small-copy allowance; their preflight results are non-success, not staged or
verified pins. This is further partial 1a evidence, not closure of the ticket.

The checkout now has [proof-data replay](ARENA_TERM_REPLAY.md) in a separate
process. Without the opt-in structural policy below, its report records
`source_export_binding="UNESTABLISHED"`; all modes retain
`metric_integrity_established=false`. This is partial ticket 1b, **not closure
of the source-verification or cost-integrity gate**. Its live substitution canary
demonstrates why valid exported terms cannot authorize verified source, honest
costs, rewards or promotion. The guide retains exact commands and the separate
frozen-source confirmations on Lean 4.26 and 4.34; neither is an Arena score.
The adapter's next extension adds explicit `--cold` observations: one branch per
fresh producer, a separate proof-data check for every sample, and an up-front
fixed-batch budget. It is partial ticket 1c, not authenticated costs or integration
into strict final confirmation. The source/counter trust gap remains unchanged;
see the replay guide for the exact measurement scope and live warmth canary.
The opt-in [explicit-term structural gate](ARENA_TERM_REPLAY.md#explicit-term-structural-gate--partial-tickets-1b1d)
now matches a bounded source-derived application/reference plan to the exported
proof before fresh kernel replay. It rejects unsupported syntax and structural
substitutions, including a different hypothesis of the same proposition. This
is another partial 1b/1d increment: imported syntax, source execution and honest
cost reporting remain unaudited, so it does not authorize promotion or rewards.
The opt-in [checked export-size guard](ARENA_TERM_REPLAY.md#checked-export-size-guard--partial-ticket-1d)
now compares parent-derived proof/type sizes after every fresh replay check.
It rejects growth, including larger expanded trees hidden by unchanged DAG
node counts. This is another partial 1d safeguard, tested offline and now with
[fresh native rejection/control cases on Lean 4.26 and 4.34](ARENA_TERM_REPLAY.md#native-export-size-guard-validation-2026-09-23).
It is not source-execution attestation or an audit of unmeasured
elaboration/import work. The controls passed the structural guard but retained
equal source-token counts; they are not strict-dual improvements or Arena scores.
The [premise/provider integration](ARENA_PROVIDERS.md) adds indexed lexical
retrieval and bounded nominations with declared holdout/alias/dependency
exclusions. The [bounded native exporter](ARENA_PROVIDERS.md#bounded-native-premise-extraction)
now probes nominated names in every required target-free prefix and filters
their native dependency/axiom closures. Whole-library discovery, authenticated
inventory publication and trustworthy family/split provenance remain open;
provider results are unverified drafts, never automatic training labels.

The first [frozen inventory/provider Arena pilot](ARENA_PROVIDERS.md#frozen-arena-pilot-2026-09-23)
admitted four prefix lemmas but rejected all twelve executions of three
one-token whole-proof replacements. The original/incumbent passed all eight
checks; the 185-token incumbent was retained. This is integration/rejection
evidence, not a compression gain or new canary result. The next proposal step
must target local proof states, not assume lexical relevance solves a theorem.

The [additional ipfs tactician/hammer reuse review](ARENA_PROVIDERS.md#further-upstream-reuse-review-2026-09-23)
identifies bounded scheduling, model-pinned fallback and single-flight discovery
as useful follow-ups. Do not copy its raw-text cache normalization: whitespace
inside string literals can collapse distinct inputs to the same key. Preserve
exact source identity, and never reuse discovery evidence as fresh confirmation.

The recommended order is: close the verifier/measurement trust gaps; extend
dependency-aware deletion and narrow solver replay; compare the deterministic
portfolio with bandit allocation; only then test learning on untouched families.
Continue restricted development experiments in parallel, but keep automatic
production promotion disabled until the safety gates are implemented and tested.

## 1. Success contract: validity first, then improvement in both costs

Optimize the proof of the **same declaration**, not an easier equation. Freeze
the target name, statement, binders, universes, assumptions, source prefix,
imports, dependency revisions, Lean versions, verifier and axiom policy.
For the first strict pilot, require the candidate's transitive axiom set to be
a subset of the checked reference's; any deliberate expansion is a separately
reviewed task policy, fixed before search, not a way to rescue a losing draft.
Changing a definition or equation statement is a different task: it needs an
explicit equivalence/refinement obligation and checks of affected callers in a
new context. Do not count it as proof-body compression.

Maintain two stores: a checked incumbent that is safe to return, and a bounded
search frontier of drafts/verified intermediates. A useful longer intermediate
can stay on the frontier without replacing the incumbent. The implemented
`strict-dual-v1` selector supplies the cost criterion; the full production
promotion contract, including still-missing security gates, must require:

```text
every required pin: original and candidate pass the fixed verification contract
candidate proof tokens < original AND incumbent proof tokens
every pin and confirmation stratum: heartbeats are demonstrably lower than both
all provenance, anti-laundering, resource and proof-integrity gates pass
```

Use integer token counts and raw integer heartbeat observations. Each promotion
must improve the current incumbent as well as retain the original comparison.
A shorter/slower proof, a faster/longer proof, missing version, inconclusive
measurement or valid-but-unchanged proof is **not a dual improvement**. Preserve
the original if nothing qualifies; there need not be a dual winner for every
theorem. No claim of global minimality follows from bounded search.

For discovery, retain a small Pareto frontier instead of throwing away useful
trade-offs. For promotion, do not allow a weighted score to compensate for
invalidity or regression. Report the official Arena formula separately only
when its measurements are applicable. The existing `arena-v1` router deliberately
permits trade-offs; its tests should continue to pass unchanged.

“Tokens” here means Lean proof-source tokens, not LLM billing tokens. Also track
prompt/completion tokens and generation cost separately if a model is used.
The deterministic-first workflow below needs no model/API by default.

### When the refactor changes an equation or definition itself

The default Arena path edits a theorem's proof while freezing its statement.
Do not silently narrow all future equation refactoring to that case. A separate
definition-refactoring task must freeze the original function, input domain,
dependent types, assumptions and observable behavior, then require a Lean proof
of pointwise equality (or an explicitly chosen refinement/equivalence relation)
between original and replacement. Use distinct names in a trusted comparison
environment; the original meaning must not resolve through the new definition.

Reject added side conditions, restricted domains or changes to termination and
partiality semantics unless they belong to an explicitly different user task.
Recheck affected callers on all pins: extensional equality alone does not preserve
every use of definitional reduction. Charge the replacement, new helper proofs
and transport/bridge proofs to a separately declared cost scope, and keep whole
dependency-closure build costs visible. This branch needs its own adapter and
fixtures; the current theorem-only Arena driver does not implement it. It must
not report its numbers as same-statement Arena proof compression.

## 2. Evidence we actually have

| Observation | What it establishes | What it does not establish |
| --- | --- | --- |
| `python -m jevops.arena --calibrate`: 15/15 published reference token counts match; 0/36 Lean checks run | A reproducible local reference-token counter | Worker-wide tokenizer/heartbeat parity or a score |
| [Prepared baseline](papers/completion/lean_refactor_arena/evidence/native-baseline-prepared-2026-09-22.json): 17 VERIFIED, 19 UNAVAILABLE | Native original-proof checks for those exact contexts | Full corpus compatibility |
| [Core plain-deletion trial](papers/completion/lean_refactor_arena/evidence/native-controlled-core-2026-09-22.json): 12 controls verified; all 24 candidate executions rejected | Textually unused hypotheses can affect induction and automation | Any optimization gain from the shorter rejected strings |
| [Core repaired trial](papers/completion/lean_refactor_arena/evidence/native-controlled-core-repair-2026-09-22.json): 24/24 executions verified, including 12 controls | One manually repaired warm-up proof improved both measured costs on all three pins | Automatic discovery, held-out generalization or official Arena score |
| [Fresh Core confirmation](papers/completion/lean_refactor_arena/evidence/native-strict-dual-core-2026-09-23.json): 48/48 checks, unchanged frozen runtime | The known 224 → 216 repair passes strict selection and fresh confirmation on three pins and both orders | Cold single-branch isolation, a new discovered theorem, or production safety |
| [Strata pilot](papers/completion/lean_refactor_arena/evidence/native-controlled-strata-2026-09-22.json): 12 native checks | Historical seed: 313 to 237 tokens, about 1.68% lower median raw heartbeats; simple transform: 313 to 289, about 0.20% lower | Robust population-wide speedups from these small two-repeat observations |
| [Composition pilot](papers/completion/lean_refactor_arena/evidence/native-composition-pilot-2026-09-23/report.json): 24 checks, including eight rejected drafts | Name-removal draft confirmed at 222 → 213 tokens and about 0.0594–0.0595% fewer raw heartbeats on its one pin | That the much shorter rejected drafts work, or that the tiny observed effect is a population-level speedup |
| [Repaired composition](papers/completion/lean_refactor_arena/evidence/native-composition-repair-2026-09-23/report.json): 12/12 screening checks verified; `NO_IMPROVEMENT` | A 211-token draft is valid but costs 431 more raw heartbeats per order than the 213-token incumbent; strict selection preserves the incumbent | That beating the original is enough to justify a regression against a later incumbent |
| [Historical recovery](papers/completion/lean_refactor_arena/evidence/native-historical-confirm-2026-09-23/report.json): 24/24 checks verified, including fresh confirmation | A recovered 185-token seed beats the rechecked 213-token incumbent by about 10.8% in raw heartbeats on its required pin and both orders | A newly discovered proof, global record, unseen-task result or compatibility beyond this task's pin |
| [Portable edits](papers/completion/lean_refactor_arena/evidence/native-portable-pilot-2026-09-23/report.json): 20 checks, 12 rejected drafts and eight verified control/incumbent checks | The 183-, 176- and 174-token drafts cannot replace the verified 185-token incumbent; there was no confirmation or improvement | That token savings alone are useful verified results, or that these edit rules fail in every context |
| [Isolated stdlib smoke](papers/completion/lean_refactor_arena/evidence/native-isolated-smoke-2026-09-23.json): two VERIFIED checks | The explicit rootless Docker path can run the existing native verifier on its tested host toolchain and record its policy | Full prepared-corpus isolation, separate proof authority, authenticated costs or an Arena score |
| [Full-set recorded benchmark](papers/completion/lean_refactor_arena/evidence/native-full15-benchmark-2026-09-23/summary.md): 20/36 baseline pins, 8/15 fully checked problems; 60 reported native processes including three controlled refactors | A newer single-run baseline and matched observations for the known 237-, 185- and 216-token drafts, retaining all 15 problems and missing pins | Full corpus validity, an accepted full-set token total, all-pin isolated execution, new discoveries or an official score |

The Core repair is the strongest immediate engineering lead. It removes
`have Hlen2 := UpdateStatesLength Hup`, changes `(ih Hinit ?_ ?_).2.2` to
`(ih Hinit ?_).2.2`, and removes the corresponding final `. simp_all` goal block.
Deleting the `have` alone fails. The [explicit draft](papers/completion/lean_refactor_arena/evidence/core-hlen2-repair-draft.json)
has **224 to 216 tokens, 3.57% shorter**. Median raw heartbeat reductions were
approximately **37.89%, 41.32%, 42.40%** on v4.29.1, v4.27.0, v4.26.0 respectively,
in both branch orders. These are not wall-time reductions. The repair used
diagnostics from this warm-up problem; it is development evidence, not a holdout.
The trial did not promote or rewrite a production proof.

The [provisioning record](papers/completion/lean_refactor_arena/evidence/provisioning-continuation-2026-09-22.json)
records 20 ready problem/version bindings and 16 still needing preparation.
Readiness is not verification. The finite three-process Cslib v4.33-rc2 baseline
was pending at the original review and has now completed:
[three targeted checks VERIFIED](papers/completion/lean_refactor_arena/evidence/native-baseline-cslib-rc2-2026-09-22.json).
Its restricted manifest marks the other 33 rows unavailable. Combined with the
17-check baseline, the saved receipts cover 20 distinct historical checks, not
a fresh simultaneous revalidation. Keep the fixed 15-problem/36-check denominator.
All inspected warm-ups are development data, not the unreleased full benchmark.

The newer full-set report above rechecks those 20 available baseline obligations
in one recorded experiment, rather than combining the two older baselines.
Its remaining 16 unavailable rows are eight project-revision mismatches and
eight Putnam directory/import gaps. Installing another compiler alone will not
repair either category. Prioritize exact dependency revisions and compiled
imports in the existing one-build/50 GB provisioning workflow, then rerun the
affected original controls; do not waive their pins or count missing costs as
zero. The declared source-token total is 17,595 → 17,474, but the accepted
full-set total and official score remain null. Saved-report consistency tests
recompute these claims without adding native verification.

## 3. Reuse the current framework, with explicit missing connections

| Existing component | Reuse now | Work still required for this objective |
| --- | --- | --- |
| [arena.py](jevops/arena.py), [arena_lean.py](jevops/arena_lean.py), [ArenaCheck.lean](jevops/lean/ArenaCheck.lean) | Typed context/receipts, exact pins, original/candidate checking, source tokens, axiom policy, integer budgets | Integrate trusted source admission and cold diagnostics into final confirmation; whole-run deadlines and separate definition-equivalence adapter |
| [arena_isolation.py](jevops/arena_isolation.py), [arena_staging.py](jevops/arena_staging.py) | Explicit rootless Docker policy, narrow read-only mounts, bounded kernel resources, owned cleanup; exact small-import copies within preparation headroom; live canaries tested | Full compiler/library storage compatibility and per-pin isolated corpus controls; supervisor-crash recovery; not a proof/metric honesty boundary |
| [arena_trial.py](jevops/arena_trial.py), [arena_pareto.py](jevops/arena_pareto.py) | Fixed drafts, balanced orders, strict-dual selection, frozen winner, fresh confirmation, failures retained | Cold single-branch confirmation; durable protected production promotion bundle |
| [arena_snapshot.py](jevops/arena_snapshot.py), [arena_report_audit.py](jevops/arena_report_audit.py) | Fixed source copies and bounded historical consistency checks | Protected evidence publication and execution linkage; a consistent report is not current proof admission |
| [arena_replay.py](jevops/arena_replay.py), [arena_source.py](jevops/arena_source.py) | Bounded separate-process proof-data diagnostic, cold observations, explicit-term structural matching and opt-in checked-export size guard; checker does not import candidate native artifacts | Structural matching covers only the declared small grammar; size guard covers exported data only; actual source execution and metric integrity remain unauthenticated; no source admission or promotion |
| [premise_search.py](jevops/premise_search.py), [arena_providers.py](jevops/arena_providers.py), [arena_premises.py](jevops/arena_premises.py) | Indexed lexical ranking, bounded provider nominations; all-pin native availability/type/dependency extraction for at most 64 nominated names | Whole-library discovery and trustworthy provenance/publication; evaluate useful refactors at equal budgets; metadata, native inventory observations and provider claims are not proof |
| [proof_slicing.py](jevops/proof_slicing.py), [arena_compositions.py](jevops/arena_compositions.py), [arena_rules.py](jevops/arena_rules.py), [tactics.py](jevops/tactics.py), [logic_refactor.py](jevops/logic_refactor.py) | Bounded deletion, diagnostic arity repair, allowlisted compositions/portable edits, existing bandit tactic | General syntax/dependency-aware repair, unseen-task evaluation and dual-metric wiring for remaining source-only paths |
| [solver_feedback.py](jevops/solver_feedback.py), [arena_solver.py](jevops/arena_solver.py) | Complete parser-bound multiline spans, compatible per-goal hint unions, whole-source replay and bounded frontier; native controls on 4.26/4.32 | Broader pinned-version/branch support, bounded support-set minimization and held-out dual-cost gains; nomination never substitutes for fresh selection |
| [proof_state.py](jevops/proof_state.py), [proof_replay.py](jevops/proof_replay.py) | Scoped observations, binders/metavariables, original-goal replay | Project/pin coverage; safe compound state edits, always followed by whole-proof checking |
| [router_tuning.py](jevops/router_tuning.py), [oracle.py](jevops/oracle.py), [search.py](jevops/search.py), [jev.py](jevops/jev.py) | Bounded proposals and injectable shared policy | Explicit native Arena dependencies, cost ledger and frontier; preserve full response provenance |
| [proof_metrics.py](jevops/proof_metrics.py), [expr_dag.py](jevops/expr_dag.py) | Compiled-expression size/sharing diagnostics | Obtain matching pinned Arena artifacts; these diagnostics are not currently an automatic Arena gate |
| [candidate_audit.py](jevops/candidate_audit.py), [scoped_evaluation.py](jevops/scoped_evaluation.py) | Source-bound outcomes, train/eval separation, model/fallback accounting | Real multi-project dual-cost labels and held-out transfer tests, not just existing finite grammar fixtures |
| [proof_ca.py](jevops/proof_ca.py), [seals.py](jevops/seals.py) | Checked obligations/evidence and dependency fingerprints | Wire scheduling to explicit Arena obligations without treating policy values or hashes as proof |

No second agent framework is needed. Use the existing proposal/search path;
the verifier alone emits authoritative Lean receipts, and a deterministic
promoter consumes them. Cells may coordinate `candidate -> pin checks -> audit
-> confirmation -> promotion` dependencies. Horn closure of these bookkeeping
obligations does not itself establish a Lean theorem.

Legacy helper callbacks returning `theorem_ok`/`kernel_audit` remain compatibility
paths, not new admission authorities. Introduce explicit adapters to the typed
Arena evaluator; do not let a policy-supplied flag satisfy the new gate.

### Upstream logic, hammer and tactician: adaptation decisions

The current source review is pinned to `ipfs_datasets_py` revision
`7f0d38572f92f5fc0cba7a5ddd4bef28523876f3`; exact paths, probes and limitations
are in the [provider reuse review](ARENA_PROVIDERS.md#further-upstream-reuse-review-2026-09-23).
Hammer and tactician are tracked Python modules within `logic`, not independent
Git submodules. The separate CEC submodules are not needed for this Lean path.
Do not vendor the entire logic package or enable its global providers. Adapt
small, explicitly injected contracts into the modules already listed above;
retain source revision/license provenance for any copied implementation.

| Decision / priority | Reuse and destination | Acceptance before relying on it |
| --- | --- | --- |
| Already adapted; next evaluate local edits | Hammer premise ranking and tactician eligibility/abstention → `premise_search`, `arena_providers`, `proof_state` | Premises accessible on every pin; target/alias/split exclusions; unsupported providers abstain; local replay and whole-proof checks. The whole-proof pilot found no improvement. |
| Next infrastructure, not proof authority | Context-bound single-flight discovery → existing provider/cache boundary | Identical requests coalesce; distinct raw bytes/types/policies cannot collide; bounded waits/cancellation; one charge per attempt; no cached confirmation or repeated rewards. Preserve byte limits as well as entry limits. |
| After verifier/measurement gates | Typed per-hole portfolio and bounded solver allocation → existing search/selector/bandit path | Zero means no provider work; reject wrong-hole/context hits; deadline starts before provider callbacks; preserve all failures and confirmation reserve; one isolated build at a time. Compare against fixed allocation. |
| Useful discovery adapter, not a new verifier | Hammer reconstruction hints/receipt schemas → solver suggestions and narrow replay | Emit alternatives separately; all-pin kernel/type/axiom checks; minimize support and measure both costs. Upstream fallback tactics are not general ATP-proof reconstruction. |
| Later, with admitted training data | Model-pinned learned-selector/fallback contract → existing shared policy | Missing/stale model deterministically falls back; outputs only reorder eligible actions; fixed budgets and held-out ablation. Hand-authored default weights are not trained dynamics. |
| Definition-refactoring branch only | Logic translation contracts: preservation, assumptions, feature coverage and weakest authority → a future equivalence adapter | Explicit supported Lean constructs and checked equality/refinement plus caller rechecks. Unknown feature coverage fails closed; a translation plan or solver verdict cannot discharge the obligation. |

Do not transplant permissive cache normalization/serialization, implicit global
resource schedulers, human-readable policy IDs as content identities, or stale
proposal retargeting. Their upstream semantics need not be bugs in their own
context; they do not satisfy this optimizer's exact identity and resource
contract. These adaptations are roadmap items unless marked already adapted.

## 4. Optimization portfolio, ordered by evidence and implementation cost

### A. Dependency-aware deletion **and repair** — first algorithmic priority

Start with existing coarse-to-fine slicing. Obtain syntax spans and local
dependency information from the pinned Lean environment; whitespace layout is
only a fallback proposal heuristic. Try deleting sibling blocks, intermediate
equalities, duplicated conversions and redundant local lemmas. Group mutually
dependent edits atomically. Recompute affected induction-hypothesis applications
and subgoal blocks rather than blindly removing an argument by position.

The Core repair is now a regression fixture for a restricted diagnostic/layout
heuristic. Extend it with cases where `simp_all`, typeclass search or an implicit
argument uses an apparently unused hypothesis; do not call the current helper
general dependency analysis.
Use diagnostics to propose a bounded repair, not to certify it. Start with a
small beam (for example four drafts and two repair steps) and compare its
cost against deletion-only under the same total verification budget.
Hierarchical delta debugging motivates structure-aware reduction; adapting its
oracle to proof validity and dual cost is our engineering proposal, not a Lean
performance guarantee from that paper.
[HDD, Misherghi and Su](https://www.cs.ucdavis.edu/~su/publications/icse06-hdd.pdf).

### B. Replace broad proof search with narrow replay

Probe expensive `simp`, `simp_all`, `grind`, and supported arithmetic calls with
their suggestion forms. Replay explicit supporting lemmas or a suggested
script, then delta-debug that support list. Start with `simp?`/`simp only` and
`grind?`/`grind only`; extend the existing adapter for Aesop suggestions only
where that project/version provides them. Preserve branch scope and source
coordinates. A probe's diagnostics are hints, never accepted proof evidence.
These mechanisms can reduce search; an explicit list can also be longer, so
neither suggestion nor lower heartbeats alone permits promotion.
[Lean tactic reference](https://lean-lang.org/doc/reference/latest/Tactic-Proofs/Tactic-Reference/),
[minimizing grind](https://lean-lang.org/doc/reference/latest/The--grind--tactic/Minimizing--grind--calls/),
[Aesop implementation](https://github.com/leanprover-community/aesop).

Probe capabilities at the **actual pinned versions**, not from latest docs.
If a suggestion form is absent, record unsupported capability and use another
arm; do not silently upgrade Lean or imports. Save query/discovery costs and
replay costs separately; the final proof must not invoke discovery again.

### C. Direct lemma reuse and bounded local resynthesis

Try existing exact hypotheses, reflexivity, a direct theorem application,
`simpa using`, then a small state-local search. Retrieve only declarations
accessible in the original target-free prefix at that pin. An existing general
library lemma is legitimate reuse; importing a new helper containing the answer,
using the target itself, or accessing later descendants is not.

Use bounded top-k premise retrieval keyed by environment/type information;
record the retrieved identities. LeanDojo motivates accessible-premise-aware
retrieval, while LeanTree motivates factored proof-state work. Neither licenses
forgetting shared metavariables, dependent binders or universe constraints.
Validate the replay against the original goal assignments, then the complete
theorem in every required version.
[LeanDojo](https://arxiv.org/abs/2306.15626),
[LeanTree](https://arxiv.org/abs/2507.14722).

### D. Equation normalization and local sharing — selective, not blanket

For identified algebraic/equality fragments, try directed checked rewrites,
shorter calculation chains and a direct normal-form proof. Preserve side
conditions such as nonzero denominators and domain/typeclass assumptions.
Never assume an algebraic identity applies to arbitrary dependent Lean terms.

Test whether explicit type arguments, less unfolding, or sharing a repeated
subproof reduces elaboration; keep the variant only if it later meets both
objectives. Sharing can add source tokens or enlarge a compiled term, so it is
not an unconditional win. E-graph extraction is a later bounded experiment
over a typed supported fragment, with a Lean-checked equality certificate and
whole-proof replay. Do not confuse an extraction cost estimate with measured
Lean cost. [egg](https://arxiv.org/abs/2004.03082).

### E. Cost-aware allocation, then optional learning

Use the existing bandit tactic to allocate search among the above arms; compare
it with fixed round-robin first. Arm rewards come from context-bound verified
measurements, once per unique observation, not confidence, compilation strings
or repeated cache hits. Separate invalid proofs, valid regressions and unknown
infrastructure failures. Key histories by problem family/context/incumbent and
avoid assuming stationary rewards after the incumbent changes.

A practical search reward is zero without validity, and otherwise the minimum
of token reduction and worst-pin heartbeat reduction, normalized against a
fixed baseline. Keep negative regressions visible and use attempts/wall cost
separately for allocation. Partial screening observations are not final rewards.
Final admission remains the hard gate, independent of this heuristic. Reserve
exploration and final-confirmation work so promising but initially costly arms
are not starved. Early stopping/resource allocation is motivated by Hyperband,
not a transfer of its theoretical guarantees to Lean search.
[Hyperband](https://www.jmlr.org/papers/v18/16-558.html).

Only after deterministic data and held-out gains exist, train a small edit
selector from valid shorter-and-cheaper pairs and carefully classified
rejections. Reuse current audit/distillation modules. ProofOptimizer provides
precedent for verifier-guided simplification training; its results are not a
prediction for our corpus. An autoencoder loss or smaller embedding is not a
proof improvement. No model downloads, GPU or live model are needed for phases
0–3; missing pinned compilers/dependencies still require bounded provisioning.
[ProofOptimizer](https://arxiv.org/abs/2510.15700).

For optional model search, send an anchored span, original goal and bounded
accessible premises instead of the entire repository; request edits rather than
repeated full proofs. Cache retrieval/prefix preparation by immutable context,
deduplicate candidate sources, and preserve model identity, question version,
selected value/distributions and measured billing tokens. This may reduce model
tokens, but must be measured separately from proof tokens and Lean heartbeats.

For the text/Lean-IR autoencoder, preserve a token cross-entropy reconstruction
objective and a separately reported semantic/cosine objective; do not replace
either with the size reward or a fuzzy proof score. Add verified compression
pairs as teacher targets only after training-split admission. A Jev/TypeSafe or
neurosymbolic-cellular surrogate may supply auxiliary gradients for lossy
outputs, but cannot certify validity or manufacture a positive native label.
Version each loss weight and learning-rate schedule; use development-only
sweeps, gradient clipping/nonfinite rejection and checkpoint rollback. Compare
CE-only, CE+cosine, and auxiliary-loss variants under matched budgets, reporting
raw decoded validity, both measured costs and fallback rates. Freeze all weights,
grammar and decisions before final family-heldout/canary evaluation. Never update
from those canaries or treat a lower reconstruction loss as an Arena improvement.

## 5. Measurement protocol and defense against optimizing the instrument

### Define the measured quantity before searching

`arena.reference_tokens` uses `lra-reference-lexical/v1`. Keep that version and
the original statement boundary in every report. Whitespace/comment deletion,
shortened identifiers or parser/tokenizer disagreement must not be presented as
structural proof compression. Add lexical differential/metamorphic tests for
comments, escaped identifiers, Unicode, qualified names and custom notation;
compare with the organizer worker when available. Fifteen matching references
are useful calibration, not exhaustive tokenizer correctness.

The current native driver measures the raw counter around synchronous
**one-command elaboration**, forcing the theorem value. Parsing precedes this
interval; prefix construction and the transitive axiom audit are outside it.
It disables async elaboration and kernel-skipping options. User-facing Lean
heartbeats use units of 1,000 raw heartbeats. Heartbeats are not milliseconds,
machine instructions or end-to-end runtime.
[Pinned Lean heartbeat implementation](https://github.com/leanprover/lean4/blob/v4.27.0/src/Lean/Util/Heartbeats.lean).

Compare reference and candidate only within the same pin/method/options.
Do not divide these raw counts by published Arena counts with an unconfirmed
measurement scope. Store raw arrays, units and method identity, not just a
rounded percentage. Add separately measured total wall/CPU time, peak memory,
prefix/parser/audit/export work, compiled-term DAG size and generated auxiliary
declarations. Track preparation/fingerprinting overhead separately from proof
execution. Faster measured elaboration achieved by moving computation into an
unmeasured helper, macro, parse phase or external worker does not count.

Existing proof-expression diagnostics need explicit pinned-artifact integration.
In the first strict pilot, require no term-DAG growth and no unexplained added
dependencies/auxiliary work; quarantine exceptions for review, not silent
automatic promotion. Use a predeclared wall/memory tolerance measured from
controls to flag displaced costs. These are extra safety guardrails, not
components secretly added to the official Arena formula.

### Discovery and confirmation must be different experiments

1. Freeze task set, candidate caps, seed, metric/trust versions and total budget.
   Establish original-proof controls and resource variability for each pin.
2. Use cheap intake and single-pin screening during discovery. A version-local
   pass is provisional. Retain every failure and cost; it is not a zero-cost
   discarded trial.
3. Freeze the finalists before inspecting confirmation results. Repeat original
   and finalist on all pins with both branch orders. Five repetitions per order
   is a proposed initial confirmation design, not a significance guarantee.
4. The current selection runner uses a fresh process per sample but two independent
   environment branches within that process; process-global caches can still
   leak warmth between them. The replay adapter now has a cold single-branch
   diagnostic. Integrate it into final confirmation only after closing trusted
   source-execution/counter gates, with equivalence/audit checked separately
   against the frozen reference. Report cold and warm protocols separately;
   diagnostic kernel replay alone does not authenticate the measured source.
5. In each version/order stratum require
   `min(control_raw) - max(candidate_raw) > delta`, where `delta` is at least
   the larger observed range and a predeclared control-derived noise floor.
   Integer token savings must be at least one. Calibrate/freeze the noise floor
   before finalist selection; never tune it to admit a favorite. An overlapping
   result is inconclusive, not a win or theorem rejection.
6. The current `arena_pareto.heartbeat_relation` and `_dominates` implement
   the range/floor comparison and strict-both gate. Fresh confirmation uses the
   same rule. The older trial `_comparison` retains its descriptive Pareto
   summary; do not confuse either with a statistical test or production
   promotion. A range rule is not immunity to selection bias.
7. If repeating an inconclusive trial, reserve a predeclared extra batch and
   include all observations. Do not keep running until one lucky minimum wins.
   For research claims, use paired task-level intervals and disclose multiple
   comparisons; performance confirmation is not a mathematical proof.

No finite budget may omit the expensive pins/repeats and still return a promoted
candidate. Count cache hits as reused evidence, not independent measurements.
Cache applicable validity for discovery; bypass observation caches for fresh
confirmation. Changes to rules/options/dependencies start a new context and
invalidate relevant receipts. An unrelated scheduler tick must not do so.

## 6. Anti-reward-hacking contract and adversarial tests

Kernel acceptance is necessary but not the whole specification. A correct
proof of the wrong statement, an allowed theorem with laundered measured work,
or a forged report can still optimize the wrong thing. The threat model includes
adversarial generated Lean and contaminated training/retrieval, not only buggy
transformations. Trusted components are the fixed task specification, pinned
toolchain/dependencies, verifier/promoter code and protected receipt storage.

| Attack or failure | Current protection in this checkout | Required addition / acceptance test |
| --- | --- | --- |
| Delete assumptions, weaken equation, change universes, prove another name | Exact statement boundary; target exists as a theorem; exact elaborated type/universe comparison; closedness checks | Mutate each binder/type/universe/name independently; no reward or promotion; definition changes go to a different task |
| `sorry`, new axioms, kernel-skip flags or native bypass | Intake rejects known shortcuts; driver fixes options; transitive axiom audit and policy | Test quoted/aliased/macro routes and all generated helper declarations; reject policy-exceeding axioms even if Lean returns success |
| Reuse target or later lemma containing the answer | Original prefix only; target must be absent; exact project/dependency pins | Negative fixture for renamed target alias and descendant import; record dependencies of every reused premise |
| Add commands/imports/options or hide computation in syntax | Bounded lexical intake; exactly one declaration parsed | Add supported syntax/expanded-environment allowlists; fail closed on unsupported forms; lexical regex is not a sandbox |
| Save tokens by shifting proof into a new helper/import/macro | Frozen prefix/import context; no added top-level commands | Audit environment delta and auxiliary declarations; charge all new proof work; distinguish legitimate existing-library reuse |
| Reset counters, spawn async work, exploit branch warmth | Async disabled, raw counters, bounded outputs, both branch orders | Single-branch fresh confirmation; reject counter-control/IO access, detect out-of-interval work; test known warm-only false gain |
| Forge stdout/receipt, replay a win or alter metrics after measurement | Typed request/source/context identity; strict numeric validation; cache/idempotency tests | Protected report channel and writer; reject duplicate/extra markers and changed binary/options; full test of proposal attempting to author a receipt |
| Modify files, use credentials/network, run an external helper | Optional rootless Docker profile; read-only inputs, hidden home/socket, no network, CPU/memory/PID limits; live synthetic IO canaries and owned cleanup | Enable compatible prepared-corpus storage; retain trusted-image/import policy and separate checker requirement; no fallback to trusted-local |
| Mutate dependencies during checking or reuse stale cache | Pre/post fingerprints, context binding; entry and byte caps | Immutable mounted snapshots, atomic publication, source/binary/options identity captured at process launch; mutation-in-flight tests |
| Reward timeout or treat missing pin as passing | Explicit TIMEOUT/ERROR/UNAVAILABLE, integer budgets, incomplete trials | End-to-end setup/fingerprinting deadline, cancellation and retry accounting; no success reward for unknown outcomes |
| Select easiest tasks, leak test solutions, train on rejected-as-valid labels | Fixed trial schedules; finite grammar audit; split/model-binding tests | Family/dependency-cluster splits, target/near-duplicate filtering, all-task denominator, frozen final artifacts and independent recheck |

The native Arena adapter defaults to **trusted-local execution, not an OS
sandbox**. Its explicit rootless Docker profile now provides host isolation;
the separate dependency-preparation container does not enable it automatically.
Do not trust unrestricted model-generated metaprograms as producers of proof
admission or cost reports until the separate-checker/allowlist work is complete.
Sandboxing protects the host; it does not establish theorem
identity or metric honesty. Hashes bind content, but are not signatures, proof,
or protection against a malicious verifier with write access.

Add a post-elaboration environment replay check for finalists. The former
`lean4checker` project says the checker is bundled as `leanchecker` from Lean
4.28; binaries were found locally for prepared 4.28 and 4.33-rc2 toolchains.
This reuses Lean's kernel: call it an additional environment replay, **not an
independent kernel implementation**. Older pins need a compatible pinned
adapter or an explicit coverage gap. [Official checker repository](https://github.com/leanprover/lean4checker).

Latest Lake documentation also describes sandboxed challenge/solution comparison
with fixed theorem names and permitted axioms, plus optional external kernels.
Capability-probe it per required toolchain; do not assume latest commands exist
in all Arena pins. Bind any export to the exact candidate and environment, and
fail closed if a required checker cannot run. A genuinely independent kernel is
an optional additional validation path, not something JevOps currently uses.
[Official Lake validation documentation](https://lean-lang.org/doc/reference/latest/Build-Tools-and-Distribution/Lake/).

No finite adversarial suite establishes “unhackable.” State the remaining
trusted-computing-base assumptions and publish discovered bypasses/regressions.

### Separate the candidate executor from the final trust decision

A protected stdout marker or file descriptor is insufficient if adversarial
metaprograms share the verifier process: they may interfere with its state or
metric collection. The phase-1 design must run candidate elaboration in the
restricted producer, treat its exported terms/environment as untrusted data,
and have a separate trusted process reconstruct/check them against the frozen
challenge. That checker must not execute candidate initializers or load its
native plugins into the trusted process. Bind the checked export to the source,
toolchain, dependency closure and options that produced it. Replaying through
Lean in another process improves the execution boundary; it is not an independent
kernel implementation or a proof that timing was honest.

Keep the cost observer and promotion ledger outside candidate control. The
metered fragment needs an explicit supported-tactic/syntax and trusted-import
policy, plus cold measurement and environment-delta accounting; an arbitrary
metaprogram cannot be made trustworthy by asking it to report its own cost.
Generated diagnostics and retrieved text remain data, never instructions to
modify the grader, corpus, thresholds, toolchain or source snapshot. Any approved
verifier change starts a new evaluation epoch and reruns its canaries and controls.

Add release-blocking fixtures for a wrong-theorem export, a correct export bound
to different source, candidate-side receipt/ledger writes, counter interference,
hidden auxiliary work, and network/home access. Execute hostile IO fixtures only
inside the completed sandbox, not in this trusted-local adapter. An unavailable
isolation/checker capability is an explicit non-success result, not permission
to disable the gate. If a bypass is discovered, quarantine affected context-bound
recommendations, retain evidence and return to the last independently checked
incumbent pending a fresh audit; never repair a result by editing its receipt.

## 7. Search accounting, evaluation and evidence format

Use isolated run memory, immutable epoch/context IDs and integer reserved work
units. Log every attempted draft, including rejected ones, with parent/edit
identity, exact source hash, proposer provenance, pin/manifest/toolchain and
verifier identities, axiom policy, request/repetition/order IDs, full outcome,
raw costs, receipt references and budget deltas. Capture executable/source
identities at launch: the current trial's source hash at report emission is not
an attestation of loaded code. No training process may modify the promoter.

Keep generation, discovery probes, native checking, confirmation and setup
budgets separate. Reserve confirmation **before** discovery. For one finalist,
the existing balanced runner needs `2 arms * 2 orders * repeats * pins` requests:
five repeats over three pins is 60, before any extra cold-replay/audit checks.
The current selector reserves at most 128 requests per phase and 256 in total;
an explicit distinct incumbent adds a third confirmation arm. Reduce finalists
or use separately recorded bounded batches if needed; do not silently truncate.
Zero means no work, not a default.
This plan does not authorize API spend or change model configuration.

Preserve the authorized provisioning cap: downloads permitted, **one isolated
build at a time, 50 GB decimal total workspace allowance**. Keep build and
native-check ownership coordinated using the existing lock; do not change
verifier boundary files while an experiment is in flight. Stage remaining pins
sequentially if they cannot coexist under the cap; retain immutable manifests
and receipts and explicitly revalidate any rebuilt artifacts. Do not delete
shared caches or user work to make room. Preparation/fingerprinting needs its
own deadline: `--timeout` currently bounds native invocation, not the whole run.

Compare under the same problems, candidate grammars, pin coverage, budgets and
verifier behavior:

1. Identity and existing deterministic search.
2. Deletion only, then deletion plus bounded dependent repair.
3. Add narrow solver replay/support minimization.
4. Add accessible-premise/local-state proposals.
5. Same portfolio with bandit versus fixed allocation.
6. Only later: frozen learned selector versus deterministic selector and
   shuffled-label/random controls over the **same choices**.

Report per-task token savings, per-pin heartbeat arrays/deltas, strict-dual
success count, all-version validity, unchanged/inconclusive/regression counts,
native attempts, proposal calls, time/memory, setup/traversal work and API cost
only when actually measured. Include neutral/negative arms and failed originals.
Show all 15 problems and all 36 pin obligations even when unavailable. Never
use raw heartbeat sums across different Lean versions as a universal cost unit.

Freeze new training/dev/test manifests by theorem family and dependency cluster,
not random lines or renamed near-duplicates. These already inspected warm-ups
cannot become pristine holdouts. Use fresh project proofs for a held-out
experiment, then the final Arena corpus under its applicable rules. Freeze
teachers, grammar, model and selection thresholds before final evaluation;
report raw model choices separately from deterministic fallback. A failed proof
attempt is a label about that attempt, not a counterexample to the theorem.

## 8. Delivery sequence and go/no-go gates

These are roadmap tickets, not a claim that every phase is complete. Phase 0
now has the strict selection criterion and regression tests. Phase 1 has an
opt-in host-isolation slice with live canaries, not its full acceptance gate; production
promotion and the remaining trust/measurement work are still deferred. Prefer
small extensions to the modules above over a new orchestration layer.

| Phase | Deliverable | Acceptance gate before advancing |
| --- | --- | --- |
| 0 — freeze the contract | `strict-dual-v1` mode, protected specification, full outcome/cost schema and launch-time run manifest | Shorter/slower and faster/longer fixtures never promote; zero/exact budgets, missing pins and duplicate receipts handled; legacy modes unchanged |
| 1 — close trust/measurement gaps | Isolated native checking, syntax/environment-delta audit, end-to-end deadline, fresh single-branch confirmation and applicable checker replay | Adversarial matrix passes; warm-only gain rejected; tampered/failed control invalidates experiment; no unsupported pin is silently waived |
| 2 — automate the demonstrated repair | Span/dependency-aware cuts plus small diagnostic-guided repair beam | Reproduce Core compound repair without using its expected answer as a search hint; reject isolated broken cuts; test unseen induction shapes at matched budget |
| 3 — widen the deterministic portfolio | Version-tested solver replay/minimization, direct lemma use and scoped resynthesis | All-pin receipts and dual measurements for every retained winner; ablate each arm on frozen development tasks; keep neutral results |
| 3b — equation/definition-changing tasks | Separate equivalence/refinement adapter, old/new environment binding, caller rechecks and whole-change cost scope | Original-domain equivalence checked on all pins; no weakened preconditions, stale callers or uncharged helper/bridge proofs; not labeled an Arena proof-body result |
| 4 — establish generalization and efficiency | Complete remaining environment coverage; matched fixed/bandit search; untouched family-split evaluation | Improvements beyond identity/current search under equal budgets, no validity regression or dropped denominator; otherwise keep simpler baseline |
| 5 — optional research | Learned selector/distillation; typed equality saturation; independent kernel validation | Independent held-out value and explicit security/version support; reject additions that only improve training loss, fixture score or synthetic costs |

Dependency provisioning can advance independently under the existing cap, but
never during a conflicting measurement/build. Phases 0–1 precede automated
promotion; phases 2–3 may collect trusted, restricted development drafts in
parallel without labeling them production winners. Learning and equality
saturation are not prerequisites for the first useful optimizer.

The first strict-dual selection unit is implemented in the existing bounded
selector. Next, close the phase-1 trust/measurement gaps before production
promotion, and extend the existing narrow Core repair/composition proposers
to general dependency-aware edits and solver replay. These can be tested as
restricted development work without relaxing the theorem or depending on
another model.

### Phase-1 implementation tickets after host isolation

These are **not-yet-closed acceptance gates**, not claims that an isolated
process already makes candidate reports trustworthy. Keep them in the existing
native verifier, driver, trial/selector and evidence components:

| Order / component | Concrete change | Evidence required to close the ticket |
| --- | --- | --- |
| 1a — `arena_prepare` / `arena_isolation` | Stage explicitly owned, non-root-readable immutable compiler/import inputs on compatible storage; reserve aggregate bytes including copies within 50 GB; never broaden home mounts or change worker UID as an automatic fallback | Real isolated original-proof controls for every supported pin; missing storage/capabilities stay non-success; no changes to shared cache permissions or overlapping builds |
| 1b — native adapter / trusted checker | Freeze a target-free challenge; capability-probe export/replay tools per pin; produce bounded untrusted proof data in the container and check it in a separate trusted process without candidate native code/initializers | Wrong target, axiom expansion, malformed/oversized export, stale dependency and source/export substitution all fail; applicable original and valid candidate pass on each required pin; unsupported pins block promotion |
| 1c — Lean driver / trial runner | Add one measured branch per fresh process; freeze reference/type audit separately, keep both existing-order controls, reserve extra invocation units and version the measurement method | Identity controls establish a precommitted noise floor; a known branch-warmth-only gain fails; no cached receipt is counted as a fresh observation; cold results cannot be mixed with the old denominator |
| 1d — intake / metrics / promoter | Define supported syntax and trusted transitive tactic implementations; audit environment delta, added proof DAG/dependencies and parse/audit/export costs; keep cost observer and promotion ledger outside candidate authority | Counter-reset, hidden helper/parser work, new import, forged receipt and candidate ledger-write fixtures cannot produce a promoted result; unexplained cost displacement is quarantined |
| 1e — adapter / resource ledger | Bound setup, fingerprinting, export/checking and cleanup under separately reserved integer budgets and a whole-run deadline; record ownership before launch | Zero/exact budgets, cancellation, daemon loss, supervisor crash, duplicate replay and concurrent host-mutation fixtures have explicit outcomes with no duplicate charges or false success |

Close 1a before attempting prepared-corpus hostile-IO canaries. Develop 1b on a
small installed pin first, but do not extrapolate that success to older exports
or the full corpus. Checking a proof export establishes validity of that data,
not automatically of the measured source: source/export linkage remains a
separate required test. After 1b, complete 1c–1e before automatic promotion.
These controls reduce stated risks under their trusted-platform assumptions;
none establishes universal immunity to reward hacking.

The highest-value **algorithmic** follow-up remains goal/dependency-aware repair:
the portable pilot demonstrates that removing an unfold or introductions can
break a goal despite reducing tokens. Use its rejected drafts as failure cases,
not training successes. Pair native diagnostic-driven repair with minimized
solver replay, then compare the same portfolio under fixed and bandit allocation.

### Next bounded experiment and artifact contract

Use the source bundles and existing selector, not a new agent framework. Freeze
four candidate slots per task: dependency-aware cut/repair, minimized solver
replay, direct accessible-lemma/local proof, and a composition of these. An
unsupported arm records abstention; do not fill it after seeing native outcomes.
Search/probe costs precede the fixed selection batch and remain separately
reserved and logged. Discovery may retain a shorter/slower intermediate, but
only the full strict gate may replace the incumbent.

With three pins and the original as incumbent, four drafts require 60 screening
requests (five arms × two orders × two repeats × three pins), plus 60 reserved
confirmation requests (two arms × two orders × five repeats × three pins):
**120** total. With a distinct incumbent, the same design is **72 + 90 = 162**.
These are proposed budgets, not executed trials or authorization for extra API
spend. Reserve separately any cold-check/audit work introduced by phase 1. No
final confirmation begins unless all required capacity and capabilities exist.
The current two-repeat historical experiments retain their original settings;
do not retroactively describe them as this five-repeat design.

Each completed experiment must retain: frozen specification/corpus/split and
source snapshot; exact candidates and edit paths; precommitted protocol; all
requests/receipts including failures; per-pin raw arrays and source-token counts;
environment/axiom and, when implemented, term-DAG/resource audits; confirmation
commitment; consistency report; and explicit promotion decision. Shared cells
can index these artifacts and unmet obligations, but cannot fabricate them.

Run the same fixed choices under round-robin and bandit allocation before adding
learning. A success is an all-pin, freshly confirmed strict-dual improvement
under matched total search/probe/check budgets, not simply more generated drafts.
Inspect the existing 211-token regression as a canary: a later candidate must
beat its actual incumbent's heartbeat cost too. Preserve the historical
213-versus-211 test, but use the newly recovered **185-token seed** as the
incumbent for new `extractedOldExprInVars` development trials, after rechecking
it under the new protocol; do not silently regress to the older baseline.
Keep the simplest allocation
if it ties or outperforms the bandit. Use a fresh family/dependency-cluster split
for transfer claims; existing public warm-ups are development data only.

## 9. Reproduction and checks performed for this plan

Offline commands recorded during the original 2026-09-22 review (the fresh
2026-09-23 audit is listed separately below):

```bash
python -m jevops.arena --calibrate
# 15/15 reference token matches; 0/36 native checks; worker parity UNCONFIRMED.

python -m pytest -q -rs --test-seal=off tests/test_arena.py tests/test_arena_trial.py tests/test_arena_lean.py tests/test_arena_module_audit.py tests/test_solver_feedback.py tests/test_candidate_audit.py tests/test_scoped_evaluation.py
# 238 passed, 100 skipped in 9.50s.
```

Ninety-nine skips are explicitly opt-in native cases; one requires cached
Mathlib. These tests cover existing implementation and saved-report integrity,
not the proposed features or a fresh recheck of historical Lean results. The
full repository suite was not run for this documentation review.

Existing offline command to inspect a reproducible repair schedule:

```bash
python -m jevops.arena_trial --plan --problem Core.InitsUpdatesComm \
  --candidate papers/completion/lean_refactor_arena/evidence/core-hlen2-repair-draft.json \
  --proposal-cap 0 --repetitions 2 --seed 17
```

Native rerun is explicitly opt-in, requires the prepared pinned manifest, holds
the owned workspace lock and writes a **new** evidence file. The exact command
and historical results are in [controlled trials](ARENA_CONTROLLED_TRIALS.md).
Do not mistake the offline plan for execution. `strict-dual-v1` is now an
implemented selection objective in `jevops.arena_pareto`; cold single-branch
confirmation and general dependency-aware repair remain proposed features.
The narrower diagnostic-guided arity repair is now implemented as proposal-only.

The plan's completion means the objective, evidence, implementation sequence,
research basis and falsifiable gates are specified. It does not mean those
future gates are implemented, every proof will improve, or reward hacking has
been eliminated.

Original documentation-only pass: all relative file links resolved; the offline repair
plan command emitted 24 scheduled requests with plan ID
`dc5b36efadbec8d9fd618d1fd32dbba8afa930b66eb5542fcc63ee3ca4b9c3b6`;
whitespace checks reported no issues. That pass changed no verifier source,
production proof, model configuration or optimization loop. Subsequent code
changes are described by the implementation follow-up above.

## 10. Completion audit of this planning deliverable, 2026-09-23

This audit covers the requested **comprehensive plan**, not completion of its
implementation roadmap. The previous implementation turn was concrete progress:
it added a source-bound proposer and preserved a fresh native confirmation.
This pass reinspected the live checkout, including subsequent composition and
report-audit work; no historical commit was restored and no existing changes
were discarded.

| Requirement of the plan | Where it is specified and supporting evidence | Current implementation boundary |
| --- | --- | --- |
| Reduce both costs, not a weighted substitute | Section 1; `strict-dual-v1` in `arena_pareto`; strict/equal/regressing fixtures and actual 211-token incumbent regression | Selection implemented; automatic production promotion remains off |
| Preserve Lean correctness and intended equations | Sections 1 and 6; `ArenaCheck.lean` checks target, exact type/universes, closedness and axioms; separate definition-equivalence branch specified | Theorem path implemented for prepared pins; definition-changing adapter proposed |
| Use the existing JevOps framework | Section 3 maps each module and missing connection; sections 7–8 bind cells/bandits to explicit obligations and receipts | No new parallel agent framework or policy proof authority |
| Explain how to save tokens and heartbeats | Section 4 orders deletion/repair, narrow replay, accessible lemmas, local synthesis, sharing/normalization and cost-aware allocation | Narrow repair/compositions measured; general dependency analysis and portfolio wiring incomplete |
| Ground methods in computer-science literature | Primary sources in section 4 re-opened for this audit: HDD, LeanDojo, LeanTree, egg, Hyperband and ProofOptimizer; Lean/Aesop primary documentation | Motivation and scoped adaptation, not imported guarantees of Lean speed or corpus gains |
| Resist reward hacking beyond passing tests | Section 6 attack matrix, producer/checker separation, immutable challenge, protected costs/ledger, quarantine and release-blocking tests | Host isolation, separate proof-data replay, cold observations and bounded structural matching exist as partial gates; trusted source execution, honest counters and cost-displacement audits remain open |
| Measure genuine improvements reproducibly | Sections 5 and 7; fixed snapshots, full failure denominator, frozen winner, all-pin controls, raw counts and fresh confirmation | Historical Core/Strata recommendations are local results; no official score, statistical certainty or independent-kernel claim |
| Make search resource-bounded | Sections 7–8; integer reservations and exact 120/162-request sample designs verified against `selection_plan` | One-build/50 GB allowance preserved; full setup deadline and extra isolation/audit budgets are explicit work items |
| Evaluate methods fairly and avoid contamination | Section 7 matched baselines/ablations and family/dependency-cluster splits; section 8 stop/keep-baseline rules | Public warm-ups are development data; held-out campaign remains future work |
| Provide an actionable sequence and handoff | Section 8 deliverables, dependencies, go/no-go gates and required evidence bundle | Phase 1 is the next release-blocking priority; restricted proposer research may continue without promotion |
| Enable pytest seals without substituting cached evidence for proof | Section 11; `pytest.ini`, `pytest_seals.py`, `test_seals.py`; explicit native opt-outs and fresh fixture closure | `on` is the default, `reuse` remains compatible, and native/benchmark checks are excluded from historical-pass reuse |
| Review reuse from upstream logic, hammer and tactician | Section 3 adaptation matrix and pinned source/probe review in `ARENA_PROVIDERS.md` | Bounded retrieval already adapted; explicit scheduling/cache/model/translation contracts proposed with counterexamples and acceptance tests; no wholesale dependency import |

The research basis was checked against the linked authors' papers and official
Lean/Aesop sources, not third-party performance summaries. In particular,
the [pinned heartbeat implementation](https://github.com/leanprover/lean4/blob/v4.27.0/src/Lean/Util/Heartbeats.lean)
confirms the raw/user-facing unit distinction. The
[current Lake validation documentation](https://lean-lang.org/doc/reference/latest/Build-Tools-and-Distribution/Lake/)
describes sandboxed comparison and warns that checking a supplied export alone
does not establish its relationship to workspace source. This motivates the
explicit export/source binding requirement above; it does not show that those
commands exist in every old Arena pin or that JevOps already uses them.

Fresh commands actually run in this audit:

```bash
python -m jevops.arena --calibrate
# 15/15 reference-token matches; 0/36 native checks; worker parity UNCONFIRMED.

env -u JEVOPS_ARENA_NATIVE_TESTS python -m pytest -q -rs --test-seal=off tests/test_arena.py tests/test_arena_pareto.py tests/test_arena_trial.py tests/test_arena_report_audit.py tests/test_arena_snapshot.py tests/test_arena_compositions.py
# 367 passed, 3 explicitly opt-in native cases skipped in 1.52s.
```

Programmatic `audit_report` checks of the saved Core confirmation, composition
pilot and repaired composition all returned `CONSISTENT`, with zero fresh native
processes. Core used its embedded plan for that consistency check; the two
composition runs also matched their separately stored protocols. Such agreement
cannot authenticate fabricated reports or revalidate current dependencies.
Programmatic `selection_plan` checks verified 60+60=120 and 72+90=162 requests
for the proposed budget designs, using unverified synthetic drafts and no Lean.
The section-9 offline Core schedule command was rerun and still emitted 24
planned requests for two arms, without executing Lean. All 40 local file links
resolved; the document has all ten numbered sections and no whitespace errors
reported by `git diff --no-index --check /dev/null LEAN_TOKEN_HEARTBEAT_SAFETY_PLAN.md`.

This pass changes only this plan. No native experiment, dependency build or
download, model-provider call, training, proof rewrite or production promotion was
started. The complete repository suite was not run. The current implementation
is not claimed to be reward-hacking-proof; the plan explicitly names the missing
controls and the evidence required before making a stronger release claim.

### Final goal audit after isolation and historical-seed recovery

The preceding implementation turn was **progress**, not a wait: it added the
opt-in host-isolation profile, ran real canaries and saved two native smoke
receipts. This continuation re-audited the user-requested **planning objective**
against the current checkout. It did not interpret completion of the plan as
completion of all its future implementation gates.

The requirement-by-requirement audit above still holds, with these verified
updates: section 2 now includes the recovered 185-token incumbent and all 12
rejected portable-draft executions; section 3 includes the actual isolation and
portable-rule modules; section 8 breaks the remaining trust work into ordered
tickets 1a–1e, each with concrete acceptance evidence. The next search baseline
is no longer the superseded 213-token proof. The valid-but-slower 211-token
case remains a historical regression fixture, not the current incumbent.

Current source inspection confirmed that strict selection checks both original
and incumbent, with all-stratum heartbeat separation and no axiom expansion;
the Lean driver still checks exact types/universes but uses two branches in one
process. The isolated smoke explicitly records `separate_proof_checker=false`.
Thus the missing producer/checker and measurement safeguards are genuine open
implementation requirements, not silently satisfied by a test count or hash.

Fresh offline command for this final planning audit:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q -rs --test-seal=off \
  tests/test_arena.py tests/test_arena_pareto.py tests/test_arena_trial.py \
  tests/test_arena_report_audit.py tests/test_arena_snapshot.py \
  tests/test_arena_compositions.py tests/test_arena_rules.py \
  tests/test_arena_recovery_evidence.py tests/test_arena_lean.py \
  tests/test_arena_isolation.py tests/test_solver_feedback.py \
  tests/test_candidate_audit.py tests/test_scoped_evaluation.py
# 591 passed, 95 skipped in 10.69s.
```

The 95 skips comprise 85 opt-in native cases, nine opt-in Docker cases and one
cached-Mathlib case. These fixtures test existing behavior, not the unfinished
release gates. Calibration again matched 15/15 reference token counts with zero
native checks; the section-9 schedule again produced the same 24-request plan.
The five saved strict-selection reports (Core, first composition, repaired
composition, historical recovery and portable follow-up) recomputed as
`CONSISTENT`; this added **no native verification**. Baseline/trial status counts
in section 2 were also recounted from their saved JSON. The 120/162-request
designs were rechecked using `selection_plan` and unverified scheduling fixtures.

The six cited research papers and official Lean/Aesop/heartbeat/checker sources
were re-opened; their use here remains method motivation, not borrowed corpus
performance guarantees. All 48 local file links resolve and all ten numbered
sections are present. No verifier source, production proof, model or loop was
changed in this final audit; no native execution, build or dependency download
was started. The full repository suite was not run.

**Planning completion:** the objective, existing evidence, concrete cost-reduction
methods, equation-equivalence branch, measurement protocol, adversarial threat
model, resource limits, staged implementation, experiment budgets and release
evidence are specified and checked for consistency with this checkout.
**Not completed:** the implementation roadmap or a demonstration that arbitrary
Lean refactors are reward-hacking-proof. If any required gate is unavailable,
keep the checked incumbent and record a non-success outcome, rather than
lowering the acceptance standard to manufacture a win.

## 11. Fast test iteration with `--test-seal=on`

The supported spelling uses **two hyphens**. `pytest.ini` sets
`addopts = --test-seal=on`, and the plugin defaults to `on` outside this
repository too. `reuse` remains an alias. This does not change the acceptance
contract, lower a threshold, or make a seal a proof certificate.

```bash
# Normal development: execute stale/new tests; report historical hits as C/SEALED.
python -m pytest --test-seal=on

# Inspect state only; nonzero when any selected test lacks a reusable pass.
python -m pytest --test-seal=status tests/test_arena.py

# A release/CI evidence run must execute bodies and refresh its evidence.
python -m pytest --test-seal=refresh --test-seal-strict
```

The [seal dependency contract](TEST_SEALS.md) binds raw file bytes, AST
diagnostics, directory membership, stat signatures, Merkle roots, fixtures,
parameters, configuration, environment and declared external inputs. An
unchanged AST or mtime alone never authorizes reuse. These are conservative
whole-tree fingerprints, not a complete inference of dynamic Python dependencies.

Keep `no_seal` on native proof/metric/security tests and live provider checks;
protect shared native fixtures through `test_seal_fresh_fixtures`, including
module-audit and Docker/replay fixtures. Those tests execute fresh when enabled,
even with `on`. Skipped/unavailable checks, failed setup/teardown, unknown or
stale inputs, unavailable locking and changed toolchains cannot become reusable
passes. New native tests must explicitly declare this contract too.

Acceptance evidence for this policy is: a cold `on` run executes and seals;
an unchanged warm run reports `SEALED` without executing its body; `on`, `reuse`
and the default share the same fingerprint; source/dependency mutations rerun;
failures never replay as successes; native opt-outs stay fresh; explicit `off`
and `refresh` still override the default. `tests/test_seals.py` exercises these
behaviors in isolated subprocesses. JUnit records reused evidence as a skip,
not a new pass. Never feed a sealed hit to a heartbeat estimator, performance
confirmation, reward, or positive proof-training label.

Planning is complete when this specification and the default/test behavior are
verified. Optimizer release still requires the open gates in sections 6 and 8;
no finite test suite or plan establishes universal immunity to reward hacking.

### Observed default/seal boundary audit, 2026-09-23

This continuation re-read all eleven sections, the seal implementation/config,
strict-dual selector and replay boundary. The prior turn was progress: it added
and tested the separate-process proof-data diagnostic, including an explicit
source-substitution limitation. This audit does not count that diagnostic as
completion of the remaining production gates.

Commands executed against the current checkout, in this order:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q tests/test_seals.py
# 42 passed in 39.24s. Seal self-tests opt out: all executed fresh.

env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=refresh \
  tests/test_arena.py tests/test_arena_pareto.py tests/test_arena_replay.py \
  tests/test_arena_report_audit.py
# 282 passed, 10 skipped in 12.55s; 277 fresh passes sealed, zero reused.

env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q \
  tests/test_arena.py tests/test_arena_pareto.py tests/test_arena_replay.py \
  tests/test_arena_report_audit.py
# No seal flag: 5 passed, 10 skipped, 277 SEALED in 8.82s.

env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=status tests/test_arena_replay.py -k live
# Expected exit 1: all 10 live cases unsealed because of live_profile;
# 27 deselected, no fixture/body or native process executed.
```

The 42 self-tests cover cold/warm reuse, the default/`on`/`reuse` alias, byte and
dependency invalidation, strict rehashing, fresh failure and teardown handling,
opt-out inheritance, shared/transitive fresh fixtures, lock contention and JUnit
historical-hit reporting. The warm core run is **277 historical results, not
277 fresh successes**. Its five fresh passes were ineligible for seals; native
cases remained skipped, not cached passes. These overlapping invocations are
not additive test coverage. Timings are observations, not a statistical claim
about seal performance or Lean heartbeat savings.

Calibration again matched 15/15 reference token counts with zero native checks.
The five recorded strict-selection experiments recomputed as `CONSISTENT`
(Core, composition, repaired composition, historical recovery, portable edits);
this authenticates neither their receipts nor present-day dependencies. The
120/162-request designs were checked again with `selection_plan` and unverified
budget fixtures. The cited six research papers and official Lean/Aesop sources
were re-opened: their role remains method motivation, not inherited guarantees.
All local document links resolved; the eleven numbered sections were present.

The requested plan and actual default seal behavior are now evidenced. Only this
plan was edited in this continuation; existing code/config and concurrent changes
were preserved. No full-suite, native proof, model, optimization, provisioning or
promotion run was performed. Source/export linkage, cold measurement, cost-
displacement audits and the other phase-1 gates remain implementation work, so
automatic production promotion must remain disabled.

### Post-structural-gate and upstream completion audit, 2026-09-23

This continuation rechecked the planning objective after the explicit-term gate
was added. Sections 3, 5 and 10 now distinguish implemented diagnostics from
unclosed release gates and explicitly cover the upstream logic/hammer/tactician
review. The detailed provider review records exact-identity counterexamples,
zero-budget/target-binding adaptation requirements and a separate future
equivalence-adapter use for translation contracts. Only this plan and
`ARENA_PROVIDERS.md` were edited in this continuation; no provider code was
copied and no existing concurrent changes were discarded.

Fresh offline commands against the working checkout:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q tests/test_seals.py
# 42 passed in 38.39s; self-tests always fresh.

env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=refresh \
  tests/test_arena.py tests/test_arena_pareto.py tests/test_premise_search.py \
  tests/test_arena_providers.py tests/test_arena_premises.py \
  tests/test_arena_source.py tests/test_arena_replay.py
# 454 passed, 32 skipped in 17.43s; zero reused, zero fresh seals retained.
```

To check default reuse independently of the changing worktree, a snapshot of
`jevops`, the two source/replay test files, `conftest.py`, `pytest.ini` and
`pyproject.toml` was created at `/tmp/jevops-plan-seals-zXK9Tb/source`. It contains
120 files / 3,224,000 bytes; manifest SHA-256 is
`5841bd8afcc4afca52c47d366ede54657a937396bb3c70588ece609310fb2465`.
The following command ran from that snapshot, with an initially unused cache
and **no seal-mode override**:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/tmp/jevops-plan-seals-zXK9Tb/source python - <<'PY'
import os, subprocess, sys
cmd = [sys.executable, '-m', 'pytest', '-q', '-o',
       'cache_dir=/tmp/jevops-plan-seals-zXK9Tb/controlled-cache',
       'tests/test_arena_source.py', 'tests/test_arena_replay.py']
env = dict(os.environ)
for _ in range(2):
    result = subprocess.run(cmd, env=env, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)
PY
# First: 140 passed, 23 skipped in 2.18s; 134 fresh passes sealed.
# Second: 6 passed, 23 skipped, 134 SEALED in 1.35s; no new seals.
```

An earlier Bash `first && second` invocation reran both suites: Bash changed
`SHLVL` for its final command. A separate read-only environment comparison
identified that key change without displaying environment values. This is the
documented conservative environment boundary, not a reason to drop inputs from
the fingerprint. With identical environments, default reuse worked as shown.
Snapshot verification reported `UNCHANGED`, and its seal implementation/config
and both test files still matched the working copy byte for byte. The 134 hits
are historical passes, not fresh tests, proofs, timing samples or rewards.

Calibration again matched 15/15 reference token counts with 0/36 native checks;
the offline Core repair plan emitted 24 scheduled requests and no executions.
Primary sources for HDD, LeanDojo, LeanTree, egg, Hyperband and ProofOptimizer,
plus official Lean grind/Lake documentation, were revisited for the plan. No
native experiment, dependency build/download, model/API call or official score
was produced by this audit. These overlapping test selections are not additive
coverage or a full repository run. The comprehensive plan, default seal behavior
and pinned upstream reuse review are delivered; completing the implementation
roadmap and demonstrating robust held-out dual-cost gains remain future work.

### Post-size-guard planning audit, 2026-09-23

The previous turn was **progress**: it completed the two fresh native
export-growth canaries and two non-growing controls, preserving their limited
authority in the [replay validation record](ARENA_TERM_REPLAY.md#native-export-size-guard-validation-2026-09-23).
This audit re-read the eleven-section plan, current strict selector, Lean
target/type/axiom boundary, seal configuration/implementation, upstream reuse
review and newer full-set benchmark. Section 2 now includes the latter with its
unchanged full denominator and concrete preparation gaps. The requirement
matrix in section 10 remains the planning acceptance checklist; the phase-1
implementation tickets remain open, not completed by these tests.

Fresh commands against the working checkout:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=refresh tests/test_seals.py
# 42 passed in 38.74s; self-tests opt out of seals and executed fresh.

env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=refresh \
  tests/test_arena.py tests/test_arena_pareto.py tests/test_premise_search.py \
  tests/test_arena_providers.py tests/test_arena_premises.py \
  tests/test_arena_source.py tests/test_arena_replay.py
# 477 passed, 34 skipped in 3.33s; no seal reuse or writes (lock contention).

env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=refresh \
  tests/test_arena_benchmark_report.py tests/test_arena_report_audit.py \
  tests/test_arena_snapshot.py tests/test_solver_feedback.py
# 118 passed, 1 skipped in 12.53s; zero reused, 116 fresh passes sealed.
```

The first two invocations overlapped: the broad regression suite correctly
fell back to fresh execution when the seal writer lock was held. This is not
evidence of cache reuse. A separate cold/warm demonstration used the unchanged
read-only source snapshot `/tmp/jevops-export-size-live-mobJEK/source`, whose
seal implementation, configuration and both selected test files matched the
checkout byte-for-byte. From that snapshot directory:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/tmp/jevops-export-size-live-mobJEK/source python - <<'PY'
import os, subprocess, sys
cmd = [sys.executable, '-m', 'pytest', '-q', '-o',
       'cache_dir=/tmp/jevops-plan-audit-seals-L5617H/cache',
       '--basetemp=/tmp/jevops-plan-audit-seals-L5617H/tests',
       'tests/test_arena_source.py', 'tests/test_arena_replay.py']
env = dict(os.environ)
for _ in range(2):
    subprocess.run(cmd, env=env, check=True)
PY
# Cold: 163 passed, 25 skipped in 2.70s; 157 fresh passes sealed.
# Warm: 6 passed, 25 skipped, 157 SEALED in 1.68s.
```

No seal-mode flag was supplied. A subsequent `--test-seal=status` selection of
`tests/test_arena_replay.py -k live`, with the same snapshot/cache/environment,
reported all 25 native cases unsealed because of `live_profile`, with 107
deselected and expected exit 1. It executed no fixture or native process.
The snapshot's retained manifest SHA-256
`a73eeae9fa4a8a39f135b7b7c23ad405880ac63cc6c8d60c7c7f2596f5a5fc72`
verified `UNCHANGED` after the runs. These 157 hits are historical local test
evidence, not additional successes, Lean receipts, measurements or rewards.

Upstream HEAD still matched `7f0d38572f92f5fc0cba7a5ddd4bef28523876f3`, with
no changes in the inspected hammer/tactician paths. Reinspection confirmed the
documented raw-text normalization, permissive serializer, unbounded flight wait,
zero-limit fallback, hole-ID retargeting, policy-label identity and ambient
scheduler constraints. The reuse decisions remain bounded adaptation of
retrieval, proposals, scheduling and fallback contracts, not copying those
incompatible authority/identity semantics or importing the full logic stack.

Calibration again matched all 15 reference counts with zero native executions;
the Core plan again scheduled 24 requests without running them. The 120/162
budget designs were checked through `selection_plan` using explicitly unverified
scheduling fixtures. The six research sources in section 4, pinned heartbeat
implementation and official grind/Lake guidance were revisited; they motivate
the stated adaptations, not guaranteed JevOps gains or availability on old pins.

Only this plan was edited in this audit. No native experiment, build, download,
model call, training, promotion or full repository test run was performed.
The requested planning deliverable, default seal behavior and upstream reuse
assessment are verified; implementation of the remaining release gates and
robust held-out dual-cost improvement are still explicitly future work.
