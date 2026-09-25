# Lean Refactor Arena: research-backed optimization plan

Research date: **2026-09-24**. This is a proposed implementation and evaluation
plan, not a report of newly implemented optimizations or newly run trials.
The authoritative checkout is commit `2c52171e2f54bfa420177db4338ce29fb3276cb8`
plus its extensive existing tracked/untracked changes. Nothing is reset.

This updates the algorithmic priorities in
[the original plan](LEAN_REFACTOR_ARENA_IMPROVEMENT_PLAN.md), using the subsequent
native results. The [strict-dual safety contract](LEAN_TOKEN_HEARTBEAT_SAFETY_PLAN.md)
remains available for that separately named objective; its verifier/integrity
requirements and documented measurement limitations also apply to the new
aggregate mode. Its requirement that both costs decrease does not. Research
sources motivate experiments; their reported gains are not forecasts for JevOps.

## 1. Recommendation

Develop JevOps into a **bounded, proof-checked optimizer of existing proofs**,
with a separate search stage and final-proof extraction stage. Concentrate first
on four interventions:

1. Select regions with realistic optimization opportunity, not just the shortest
   captured tactic spans.
2. Match lemma conclusions and arguments in Lean, rather than treating overlap
   among constant names as evidence of applicability.
3. Search with bounded automation, then extract and minimize the successful
   proof. The search procedure need not itself be the final proof source.
4. Generalize dependency-aware, coupled repairs around induction and local
   hypotheses, which already have a positive development example here.

Add historical strategy retrieval, model proposals and adaptive budget
allocation after those components have measurable standalone value. Keep the
existing JevOps orchestration and adapters; do not add another agent framework
or make a neural score authoritative.

Objective update: the latest request prioritizes **aggregate Arena score**,
allowing a modest size increase when normalized heartbeat savings compensate,
or the converse. The same theorem and every required version remain hard
constraints. The earlier strict-dual objective remains an explicit control,
not the aggregate acceptance rule. The implemented opt-in
`aggregate-local-v1` selector and `discovery-aggregate-v1` nomination are
documented in [aggregate selection](ARENA_PARETO_SELECTION.md#aggregate-local-score-opt-in).
Official Arena scoring remains separate, subject to measurement parity; local
reference-normalized estimates must not be presented as leaderboard results.
The older strict-dual experiments below retain their original interpretations.
For non-original seeds, the new opt-in
[`discovery-reference-v1`](ARENA_SOLVER_SPECIALIZATION.md#original-reference-nomination)
uses original-normalized discovery weights without extra verifier calls.
The separate [fixed Strata confirmation](papers/completion/lean_refactor_arena/evidence/solver-reference-strata-2026-09-24/README.md)
passed 30 fresh checks and improved the incumbent's local combined score by
2.76779 points (five more tokens, about 11.84% fewer heartbeats). This confirms
one previously generated draft, not a causal comparison of nomination policies
or a whole-corpus/official score improvement.

## 2. What the current evidence says

### Latest local portfolio

The [frozen report](papers/completion/lean_refactor_arena/evidence/local-tactic-portfolio-2026-09-24/report.json)
and [diagnostic summary](papers/completion/lean_refactor_arena/evidence/local-tactic-portfolio-2026-09-24/summary.json)
establish the following historical observations:

| Observation | Consequence for this plan |
| --- | --- |
| 37/37 selected local observations captured; all four original replay baselines checked | Observation repair worked for this task; repeating that repair is not the next search intervention |
| Baseline 0/2 and portfolio 0/2 all-pin-valid drafts | No measured Arena improvement from this portfolio yet |
| `updatedStatesInit` proposed for a `List.Nodup` goal | Conclusion applicability needs more than lexical relevance |
| `assumption` proposed without a matching local hypothesis | Cheap symbolic preconditions can avoid some wasted attempts |
| Portfolio emitted `exact` and `assumption`, no guarded-application draft | Family rotation does not guarantee useful family coverage under a finite, strict-shortening cap |
| 9 versus 66 template attempts, but 31 versus 9 rankings | Reduced template work did not establish a speedup; setup/retrieval work also matters |
| 15 native launches, 404.9912 s, no survivors for measurement | Verification/discovery cost is material; no heartbeat gain or official score follows |

The positive synthetic argument control improved from 0/2 to 1/2 accepted
candidates on both tested Lean versions. That validates a mechanism, not its
benefit on real Arena tasks.

Inspection of `arena_providers.py` shows a further restriction: final-source
token filtering is applied directly to generated search scripts. A long guarded
application can therefore be discarded before native search discovers a short
explicit term. Removing this restriction from **bounded discovery**, while
retaining it for final acceptance, is a distinct experiment.

### Stronger historical leads and coverage gaps

The latest consolidated baseline report inspected here records **26/36 pins
and 9/15 fully checked problems**, not complete readiness. Its remaining gaps
include ArkLib commit/source-location mismatches and older Putnam environments.
These are infrastructure/provenance outcomes, not failed mathematical proofs.
[Recorded full-set summary](papers/completion/lean_refactor_arena/evidence/native-full15-putnam-continuation-2026-09-23/report/summary.md).

The same report retains known refactors, including `Core.InitsUpdatesComm`
at 224→216 tokens and approximately 37.9–42.4% lower measured raw heartbeats
across its three pins. The important transformation removed `Hlen2` **and**
repaired the induction-hypothesis application and corresponding goal block.
Deleting that hypothesis alone failed. Other known incumbents include the
237-token `substOldPostSubset` and 185-token `extractedOldExprInVars` proofs.
These are historical development results, not fresh checks or new discoveries.

Every new optimization must compete against the appropriate freshly checked
incumbent, not merely rediscover an improvement over the original.

## 3. Research findings that affect the design

### A. Symbolic optimization passes are directly relevant

Limperg's 2026 talk describes proof optimization organized like compiler passes,
using syntax and elaboration information to remove redundant proof structure.
It also highlights invalidated source-position information and nonlocal effects
from metavariables. The presented implementation was described as internal; its
availability must not be assumed. We can implement compatible ideas using our
existing adapters. [Symbolic Proof Optimisation for Lean](https://leaning.in/2026/slides/limperg.pdf).

Mathlib's public tactic-analysis framework can inspect tactic sequences and
test replacements with cost observations. Its current passes include adjacent
rewrite merging, terminal replacement and suggestion checking. The interface
is explicitly not guaranteed stable, so inspect/probe the actual project pin
before adapting it. Do not add Mathlib to a task that did not import it.
[Framework](https://leanprover-community.github.io/mathlib4_docs/Mathlib/Tactic/TacticAnalysis.html),
[passes](https://leanprover-community.github.io/mathlib4_docs/Mathlib/Tactic/TacticAnalysis/Declarations.html).

### B. Retrieval must support actual proof construction

LeanDojo/ReProver motivates accessible-premise extraction and challenging
negative examples. LeanHammer goes further with dynamic local-project facts
and training data that includes premises used implicitly by automation, rather
than only the next visible tactic. These are useful data-design lessons; their
learned retrievers and external prover stacks are not required for our first
typed-matching experiment. [LeanDojo](https://arxiv.org/abs/2306.15626),
[LeanHammer](https://arxiv.org/html/2506.07477v2).

### C. Search once, retain a smaller proof

`aesop?` can emit a proof script, with documented reliability limitations.
Lean's `simp?` identifies a restricted simplification call; `grind?` can suggest
`grind only` or a script. These enable discovery followed by independently
checked replay without retaining the entire search. They do not guarantee
shorter text or lower cost on every pin.
[Aesop](https://github.com/leanprover-community/aesop),
[simplifier reference](https://lean-lang.org/doc/reference/latest/Tactic-Proofs/Tactic-Reference/),
[minimizing grind](https://lean-lang.org/doc/reference/latest/The--grind--tactic/Minimizing--grind--calls/).

### D. Use feedback and version-aware strategies before expensive training

COPRA motivates bounded, execution-feedback-driven backtracking. Lean Refactor
motivates a strategy bank with version and cost metadata; its version-filtering
results are not uniformly best in every setting. Both support experiments on
our existing history/prompt interfaces, not an assumption that more agents or
more retrieved text will help. [COPRA](https://arxiv.org/abs/2310.04353),
[Lean Refactor](https://arxiv.org/html/2605.20244v1).

ProofOptimizer demonstrates expert iteration/RL for simplification using Lean
feedback. It motivates collecting high-quality verified edit data; it does not
establish that training on our few reused warmup examples will generalize.
[ProofOptimizer](https://arxiv.org/abs/2510.15700).

### E. Equality saturation is selective, not a mandatory dependency

Guided equality saturation supports searching for equational rewrite chains
with intermediate guide terms. However, `lean-egg` currently marks itself
deprecated and recommends `grind`. First test the already available proof-
producing native tactics. A separate typed, bounded rewrite explorer is a later
option, not a reason to import a Rust/solver stack into the core.
[Guided Equality Saturation](https://thok.eu/publications/2024/popl.pdf),
[lean-egg status](https://github.com/marcusrossel/lean-egg).

Proof-Refactor's helper-oriented modularization targets readability and
structure. Its objective differs from Arena's cost objective. Borrow local
decomposition only when all helper work remains inside the charged proof body;
new uncharged declarations are not an admissible compression trick.
[Proof-Refactor](https://arxiv.org/abs/2606.03743).

All implementation choices below are JevOps-specific hypotheses inferred from
these sources and our recorded failures. No paper's percentage improvement is
used as an expected JevOps gain.

## 4. Proposed optimization pipeline

```text
fresh incumbent + frozen project/version context
    → syntax/goal/dependency/cost observations
    → bounded region and strategy selection
    → native search with isolated branch state
    → explicit proof/script extraction and minimization
    → complete-source checking on every required pin
    → balanced cost measurement + fixed-winner fresh confirmation
    → retained incumbent or a local improvement recommendation
```

Discovery artifacts, applicability observations, local closures, whole-proof
validity and measured improvement remain separate evidence kinds. The cellular
runtime may coordinate these obligations and resource reservations; its ground
Horn engine must not pretend to establish arbitrary Lean propositions. Lean
remains the proof-producing/checking adapter for these obligations.

## 5. Prioritized implementation work

### P0 — Freeze the objective, capability matrix and diagnostic baseline

Reuse `arena.py`, `arena_lean.py`, `arena_trial.py`, `arena_pareto.py`, snapshots
and preparation locking. For each task/pin record:

- Exact source/dependency revision, fresh original/incumbent outcome, token
  method, raw heartbeat method, and whether cost observations are trustworthy
  enough for the intended use.
- Which tactics and suggestion forms are actually available in the original
  environment. Treat latest online documentation as research, not capability
  evidence for Lean 4.26/4.27/4.29 project pins.
- Coverage losses: observation unsupported, uneditable syntax, query overflow,
  no applicable premises, tactic failure, unclosed goals, whole-source failure,
  incompatibility, cost regression, and infrastructure error.
- A separate resource ledger for native launches, native rule applications,
  heartbeats, CPU/wall time, retrieval work, and model tokens/dollars.

Resolve the ten historically missing baseline checks as a separate provisioning
workstream: investigate exact commit/source binding before building anything.
Preserve one isolated build at a time and the user's 50 GB cap; do not solve
coverage by substituting a convenient newer project or deleting unrelated caches.

Existing proof-data replay still documents source/export and counter-authority
limitations. Continue trusted-local development experiments, but keep production
promotion disabled until the applicable integrity/isolation gates are closed.
No candidate may repair an audit failure by changing the axiom policy.

**Deliverable:** source-bound capability/failure census plus a runnable fixed
baseline. Missing pins remain visible; no full-set score is claimed.

### P1 — Select regions with headroom and useful dependency structure

Extend `arena_local.py`, `proof_state.py` and the provider's event selection;
reuse existing branch/span utilities rather than introducing a second parser.

Build a source-bound region inventory for closing blocks, branches and larger
proof bodies. Record span token count, overlapping/nested spans, syntax kind,
local dependencies, automation present, and whether metavariables connect the
region to its surroundings. Add separate heartbeat observations when a native
instrumentation path supports them; do not infer heartbeat cost from source size.

Compare the current small-span-first order with deterministic headroom buckets:
longer closing blocks, redundant dependency chains, and expensive automation.
Reserve some attempts for smaller regions to avoid permanent heuristic pruning.
Do not claim an estimated minimum replacement length is a proven lower bound.

The current closing-span projection is enough for the first experiment.
Arbitrary open transitions require a later continuation-aware adapter. Shared
metavariables make syntactically separate regions potentially dependent.

After any accepted edit, re-elaborate/recapture before using new offsets. Apply
independent multi-edit batches only when source non-overlap and dependency
checks support them, then recheck the entire candidate anyway.

**Success criterion:** greater opportunity coverage and more all-pin-valid
improvements per native budget, not merely larger spans visited.

### P2 — Typed conclusion indexing and bounded native applicability

Extend `lean/ArenaPremises.lean` and `arena_premises.py` with a versioned optional
structural signature: declaration identity, telescope/binder kinds, conclusion
shape/head, relevant constants and dependency identity. Preserve the V1 text
inventory through a compatibility reader. Do not parse dependent types with
regular expressions or mistake pretty-printed text for a trusted Expr.

Separate three retrieval channels:

1. Backward application candidates whose conclusions may match the target.
2. Forward rules whose premises fit local hypotheses and can establish an
   intermediate fact.
3. Equality/iff rules relevant to subexpressions for rewriting/normalization.

For direct application, prioritize `List.Nodup` conclusions for a `List.Nodup`
goal. Keep a bounded fallback: definitions, coercions, generic lemmas and
multi-step arguments make a head-symbol filter incomplete. A forward lemma
must not be discarded merely because its conclusion differs from the final goal.

In a regenerated native state, instantiate binders and attempt application with
a fixed transparency/unification budget. Return explicit outcomes such as
`MATCHED_WITH_SUBGOALS`, `CLOSED`, `INAPPLICABLE`, `BUDGET` and `ERROR`.
An applicable lemma is not a closed proof. Every premise needs justification.

Save/restore the complete relevant native elaborator/metavariable state between
attempts, not just displayed goals. Nothing exported by Python establishes
native applicability by itself. Preserve target/alias/held-out exclusions and
all-pin environment availability.

Start with native signatures and deterministic indexing; compare dense retrieval
only later if recall remains the measured bottleneck. Reference-proof constants
can be hints in this refactoring task, but label that condition explicitly and
exclude the target itself and target-dependent declarations.

**Success criterion:** fewer wrong-conclusion attempts and more checked closures
at fixed native application/heartbeat budgets. Retrieval recall alone is not a win.

### P3 — Separate search from final proof materialization

Introduce an opt-in bounded discovery action alongside existing draft emission;
do not change `baseline-v1` or `portfolio-v1` retrospectively.

The initial grammar should compose only allowlisted operations: local/external
lemma application, constructor/projection steps, controlled rewriting,
assumption/reflexivity, and available bounded automation. Use a small AND/OR
search: all subgoals from one rule are required; alternative rules backtrack.

For the first implementation, use native snapshots inside a single owned
process for discovery only, with branch reset tests. Final screening and cost
confirmation still run fresh. Report both process count and individual tactic
applications so batching cannot hide a larger search budget.

Allow a search script to be longer than the current source. Once it closes:

- Extract an explicit term or tactic script with the actual inferred arguments.
- Resolve names in the correct scope; shorten qualification only after a bound
  native recheck confirms it still resolves to the intended declaration.
- Reject pretty-printer output that fails independent parsing/elaboration.
- Test the extracted replacement in the complete original continuation and then
  every required project pin.
- Apply the precommitted final objective to this final candidate, not to the
  search procedure that produced it: aggregate mode permits a justified cost
  trade-off; strict-dual mode requires both costs to decrease.

For example, the development control's guarded application can lead to the
explicit candidate `exact _root_.library_step h`. This is a proposed extraction
path, not a newly measured refactor from this planning turn.

A bounded frontier may keep valid longer intermediates for subsequent
optimization. Limit count, bytes, edit depth and total work; it must never replace
the verified incumbent until it passes the final acceptance contract.

**Success criterion:** cases where longer discovery yields a verified final
proof with better combined cost (or both costs for the strict control), followed
by new improvements beyond current real-task incumbents.

### P4 — Solver specialization and support-set minimization

Extend `solver_feedback.py` rather than duplicating its source-bound suggestion
pipeline. Its current parser is single-line and does not accept the full range
of emitted tactic scripts. Add bounded syntax-aware multiline handling with
exact anchors, preserving branch structure and rejecting declarations/options.

For each supported pin, compare broad automation with its extracted/restricted
form: `simp?`/`simp only`, `grind?`/`grind only`, and `aesop?` scripts when Aesop
is already available. Explicitly re-run suggestions; a compiler message is not
a proof certificate. Expand only capabilities the actual environment supports.

Minimize successful premise sets with bounded deletion/replay, and test merging
adjacent rewrites or removing redundant normalization. Maintain a small Pareto
frontier: an explicit lemma list can be faster but longer, so it may be useful
without being a strict-dual winner. Aggregate mode must let such a proof compete
as a final candidate, not only as a stepping stone toward shorter syntax.

Prefer domain-specific native tactics when the goal warrants them: integer
arithmetic, polynomial identities, constructor reasoning or congruence. Probe
their availability and keep their axiom requirements inside the fixed policy.
Do not assume `ring`, `omega`, `linarith` or `grind` dominates the others on all
versions. Do not introduce `native_decide` or unchecked external certificates
as a cost shortcut.

**Success criterion:** freshly confirmed heartbeat savings without the required
token regression; report valid faster-but-longer alternatives separately.

### P5 — Dependency-aware deletion and induction repair

Use `proof_slicing.py`, `arena_rules.py`, `arena_trial.py`'s diagnostic repairs,
and native before/after dependency information to move beyond line deletion.

Create typed edit transactions for:

- Removing an unused local fact and any now-redundant proof scaffolding.
- Removing an alias while repairing its actual uses, respecting binder scope.
- Reducing an induction motive/context and repairing affected induction-hypothesis
  arguments and corresponding goal blocks together.
- Replacing repeated derivation of a fact with one local proof, or undoing
  sharing when it makes elaboration or induction more expensive.
- Minimizing generalization only when the unchanged target and whole proof
  remain valid.

Textual non-use is insufficient: automation, local instances and induction
generalization can depend on a fact with no visible textual reference. Typed
dependencies narrow proposals, but each complete edit transaction still needs
native checks. Start from the existing precise arity-repair rule and add one
new repair shape at a time with negative controls.

Turn the known Hlen2 repair into a development fixture, then evaluate analogous
repairs on different theorems. Reproducing its 216-token endpoint does not beat
that endpoint as an incumbent or establish generalization.

**Success criterion:** automatically found coupled edits that beat known
incumbents, plus transfer to independently selected proof families.

### P6 — Bounded algebraic normalization and rewrite exploration

This is a second-wave experiment for genuinely equational regions. Compare
explicit rewrite chains, available `grind`/normalizers and a bounded guided
rewrite search. Use guide expressions suggested by syntax, prior checked
strategies or an optional model; Lean must prove each bridge.

Any internal e-graph must be typed and binder-aware, retain proof witnesses and
side-condition obligations, and have strict node/iteration/extraction limits.
Do not treat equality saturation as a complete optimizer of dependent Lean
proofs. Cost extraction is a heuristic; verify the extracted source and measure
its actual elaboration cost.

Never apply field identities without required nonzero hypotheses, transfer
integer rules to natural-number subtraction unchecked, or assume operations
commute. Changing the theorem statement or definitions requires a different,
explicit equivalence/refinement task; it is not Arena proof refactoring.

**Success criterion:** a controlled additional benefit over native normalization
on selected equational tasks, justifying any added complexity/dependency.

### P7 — Context-bound strategy memory and model assistance

Extend `refactor_history.py`, `refactor_prompts.py` and existing Leanstral/Meta
MUSE adapters. A strategy record should contain:

```text
strategy/version + syntactic and typed preconditions
exact source/environment identities + complete dependency pins
unverified draft → local outcome → all-pin outcome → measured cost outcome
edit family and coupled obligations + counterexamples to applicability
generation/search cost + data split + provenance + tested compatibility set
```

Keep failed tactics, timeouts and invalid proofs distinct. A lemma rejected at
one goal is not a false lemma. Deduplicate observations by immutable attempt/
receipt identity, and retain checked wins as historical examples rather than
fresh proof receipts. Compatibility observations are an empirical tested set,
not a guarantee for all versions between two tags.

Prompts should contain the frozen target, selected region with enough surrounding
scope, before-goal and locals, available lemma signatures, one relevant positive
contrast, a bounded failure summary, exact Lean diagnostics and remaining
budget. Do not silently truncate binders or required declarations. Keep search
metadata/diagnosis separate from the existing tactic-only final-body transport;
any new structured edit protocol needs explicit versioning and tests.

Compare same-source retries with typed error-aware repairs and retrieved
strategies under matched provider/model/output/call budgets. Use the existing
`coupled-repair`, `performance`, `portable` and `replan` templates as baselines,
not as features to build again. Never default to live calls or expose credentials
to Lean subprocesses.

Only after a sufficient independent dataset exists, test a small learned
strategy selector or proof simplifier. Freeze family/project splits before data
collection; retain hard failures without labelling all unchosen alternatives
as incorrect. Learned policy outputs remain suggestions.

**Success criterion:** additional confirmed wins per total search/model budget
on held-out families, not improved training loss or fluency alone.

### P8 — Adaptive allocation after a deterministic baseline

Reuse `tactics.multi_armed_bandit` and the existing budget/evidence mechanisms.
Arms should be specific transformations conditioned on goal family and
capability, not unrestricted agents. First compare uniform round-robin and
fixed quotas; then test Thompson/UCB allocation with a nonzero exploration share.

Use a once-only reward derived from an eligible, confirmed improvement, with
resource use recorded separately. Do not reward a short rejected string, a
cache hit, repeated journal delivery or an unsupported model confidence.
Pending work needs an explicit identity; infrastructure failures have their
own outcome rather than becoming mathematical failure labels.

For the aggregate objective, report the confirmed reference-normalized score
delta, not raw heartbeats saved or a binary shortest-proof count. Every problem
has equal weight in the corpus mean; a large theorem is not automatically worth
more. Compare score improvement versus cumulative native/model budget, while
reserving verification and confirmation capacity before allocation. An incumbent
replacement earns only its incremental improvement, not its entire historical
gain over the original again. This cost-aware allocation remains a later
experiment, not a capability established by the scalar selector.

Changing incumbents makes the reward process nonstationary. Bind observations
to the task/context/incumbent epoch and evaluate adaptation empirically; do
not quote stationary-bandit guarantees as guarantees for this optimizer.

**Success criterion:** better improvement-versus-budget curves than deterministic
allocation, without exhausting confirmation reserve or suppressing rare useful arms.

## 6. Experiments that distinguish the hypotheses

### Stage A: mechanism controls, offline and installed-Lean only

Add independent fixtures covering:

- Wrong conclusion despite high lexical overlap; definitionally equal target;
  implicit/typeclass arguments; a forward chain whose first conclusion is not
  the final goal; multiple required premises with one missing.
- Native branch rollback, shared metavariables, shadowed names, malformed
  suggestions and unchanged work loops.
- A long discovery script that extracts to a short valid term; an extracted
  term that pretty-prints incorrectly; a shorter but slower result.
- Tactics available on one pin but absent on another; unsafe axioms; a proposed
  dependency on the target itself; unchanged imports/options/statement.
- Paired deletion/repair, implicit induction dependencies, and failed partial edits.
- Zero/exact budgets, duplicate observations and stale context/capture rejection.

Passing these controls is required before a real task experiment. It is not
counted as benchmark optimization performance.

### Stage B: isolate retrieval and span selection

Keep the same proposal families and native resource ceilings. Use a 2×2 design:

| Arm | Retrieval | Region order |
| --- | --- | --- |
| A | Current lexical | Current small-span-first |
| B | Typed conclusion/applicability | Current small-span-first |
| C | Current lexical | Headroom/dependency-aware |
| D | Typed conclusion/applicability | Headroom/dependency-aware |

Retain the exact frozen `portfolio-v1` and legacy baseline as reference runs.
The factorial arms are new named configurations, not rewritten historical results.
Fix tie-breaking seeds and task sets; report per-theorem paired outcomes.
Count extra native applicability work against B/D, even if batched in one process.

The primary outcomes are all-pin-valid candidates and confirmed improvements
per budget. Intermediate diagnostics include applicability@k, complete-closure
rate, template rejection reasons, extraction success and costs by stage.
If typed matching improves closure but not optimization, move effort to region
choice/extraction rather than declaring the retrieval intervention sufficient.

### Stage C: extraction, repair and prompt ablations

On the strongest fixed Stage B configuration, separately compare:

1. Search script as candidate versus extracted/minimized script or term.
2. Single deletion versus coupled deletion/repair.
3. Broad automation versus minimized support set.
4. No historical examples versus relevant source-bound contrasts.
5. Fixed allocation versus adaptive allocation, only after enough observations.

Use small initial depth/node limits, then compare a second preregistered budget
level. A reasonable starting grid is depths 2/4 and 16/64 native rule applications
per region, with an additional per-problem total cap, eight final source drafts
and at most two measured finalists. These are proposed experiment parameters,
not established optimal settings; freeze them before execution.

### Budget accounting and selection

Reserve discovery, all-pin screening, repeated measurement and confirmation
before work. `selection_plan` remains the authority for its phase count. For
example, with two finalists, a distinct incumbent, three pins, two branch orders,
two screening repetitions and three confirmation repetitions:

```text
screen:       (reference + incumbent + 2 finalists) × 3 × 2 × 2 = 48
confirmation: (reference + incumbent + frozen winner) × 3 × 2 × 3 = 54
total selector ceiling = 102 calls, plus separately budgeted discovery/pre-screen
```

Only a frozen winner enters confirmation; do not adapt candidates or choose a
second-place fallback after viewing confirmation. Charge failed probes and all
extraction/minimization attempts. Report unused reserve separately. No dollar
claim is made when actual model usage/pricing is not measured.

A persistent search process is a throughput optimization only. It cannot count
warm replay/cache reuse as an independent cold cost measurement. Fresh final
verification and the documented measurement method remain mandatory.

### Stage D: broaden the task distribution

Begin with ready projects: Strata for state/induction reasoning, CSLib for
inductive and relational structure, and PhysLib for algebraic/analytic automation.
Use Putnam/ArkLib available pins for labelled development probes, but require
the remaining pins before calling their candidates all-version-valid.

Use all 15 public warmup problems in the report denominator, keeping unready
ones visible. Do not call already-inspected warmup problems blind holdouts.
Create a separate project/file/family-disjoint development evaluation set from
permitted data; exclude near-duplicate proofs and retrieved target aliases.
For learned methods, split before collecting training feedback and freeze the
policy before evaluation. Treat theorem, not local span or version repetition,
as the basic unit for aggregate uncertainty reporting.

Report all-pin compatibility, original/incumbent-relative token reduction,
per-pin heartbeat ratios, confirmed wins, neutral outcomes, regressions,
discovery costs and timeouts. With small samples use paired tables and explicit
uncertainty; do not manufacture significance from many correlated local goals.

## 7. Implementation order and acceptance checkpoints

| Milestone | Concrete work | Exit condition |
| --- | --- | --- |
| M0 | Capability/failure census; immutable trial and objective manifests | Ready subset reproduced; gaps and source/measurement trust limits explicit |
| M1 | Region inventory and structured premise signatures | Offline schema/budget/leakage tests; native matching and rollback controls |
| M2 | Bounded search → extracted proof; multiline suggestion replay | Positive extraction control plus complete rejection controls on installed pins |
| M3 | 2×2 retrieval/span trial; support minimization | Matched-budget real-task table, including negative results |
| M4 | Generalize one coupled induction/deletion repair | New checked repair beyond the memorized Core example, or a documented stop decision |
| M5 | Cross-family evaluation and history-guided model ablations | Improvement over frozen deterministic baselines at matched cost |
| M6 | Adaptive allocation; optional learned selector/equational research | Additional benefit on precommitted held-out tasks, not just warmup replay |

Keep M0 coverage/provisioning work separate from algorithm comparisons. Do not
block all deterministic experiments on a missing older Mathlib build, but do not
relax an affected task's all-pin acceptance criterion either.

A proposed go/no-go rule for a strategy: if a preregistered matched-budget pilot
produces no new confirmed gain across the selected ready tasks, inspect whether
the failure is retrieval, applicability, extraction, compatibility or cost.
Change one factor in a new experiment or retire the arm. Do not keep increasing
budgets on the same inspected theorem and call that independent validation.

## 8. Competition, integrity and scope boundaries

The organizer currently describes proof size, elaboration efficiency and
cross-version transfer as the three scoring dimensions. It lists a November 1,
2026 full-benchmark release and November 8 deadline, with a US$3/problem closed
track or a four-80-GB-A100/48-hour open track. Recheck eligibility and accounting
rules before a submission; this planning task does not authorize one.
[Organizer competition page](https://vericodegen.github.io/).

The public UI is not proof of worker/tokenizer/measurement parity. Our frozen
local scoring implementation and strict-dual recommendations must not be
presented as organizer-certified scores. Do not fabricate a full-corpus total
from partial pin coverage.

Retain these invariants throughout the work:

- Same target, statement, assumptions, imports/options and pinned dependencies.
- Target-free admission environment; fixed transitive axiom policy, with no
  expansion over the reference/incumbent where required by selection.
- Exact source-byte/context identities; no unsafe whitespace-normalized cache.
- Stale captures and historical successes cannot authorize current edits.
- No hidden helper work, changed counter settings or moved computation outside
  the charged measurement scope.
- No trusted proof flags or costs supplied by a model, tactic diagnostic or
  generic upstream solver success parser.
- Separate local success, whole-proof validity, measured improvement and
  production promotion. Existing security gaps remain visible.
- Explicit opt-in model calls, no credentials in Lean workers, bounded logs and
  attempts, and no new mandatory large dependency stack.

## 9. First deliverable to implement

The next narrow vertical slice should be **typed premise application plus
explicit-term extraction on a headroom-selected closing block**, with an A/B
switch preserving the current baseline. It should include native negative
controls, unchanged final admission, exact cost accounting, and the initial
retrieval/span ablation before any broader model integration.

In parallel, generalize the known coupled induction repair by one supported
shape. These two paths directly address recorded failure modes and an existing
positive result. They offer more informative experiments than another
unconditional tactic sweep, while leaving larger learned/ATP/e-graph ideas as
explicit, measurable later decisions.

Only this research-plan document was added for this task. No optimization was
implemented, model called, Lean benchmark run, dependency provisioned, score
submitted, or repository commit/push performed during its preparation.
