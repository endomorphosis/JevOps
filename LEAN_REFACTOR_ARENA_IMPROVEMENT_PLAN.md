# JevOps: a measured plan to compete in Lean Refactor Arena

Research and checkout inspection: **2026-09-22**. Base commit observed:
`2c52171e2f54bfa420177db4338ce29fb3276cb8`, plus the current modified and
untracked files. Those changes are part of the inspected implementation, not
discardable scaffolding. This document is a plan; it does not claim that its
proposed features, experiments, or competition submission have happened.

For the user's stricter **reduce both tokens and heartbeats** objective, use the
[focused safety and dual-improvement plan](LEAN_TOKEN_HEARTBEAT_SAFETY_PLAN.md).
Its all-version strict promotion contract supersedes the score-trading
recommendations below for that objective, without changing the Arena formula
or current executable modes. It includes the Core repair evidence, a prioritized
implementation sequence and an explicit anti-reward-hacking test matrix.

## 1. Recommendation

Build a **score-aware, proof-checked, anytime refactoring portfolio** inside
JevOps. Preserve an independently checked incumbent for every problem; use
cheap structural transformations first, goal-local search and retrieval next,
and learned proposals only where they earn their cost. Let the existing
neurosymbolic runtime coordinate explicit obligations and evidence. Lean, in
the correct environment, remains the authority for Lean proofs.

The biggest immediate opportunity is not another tactic catalog or agent
framework. It is connecting the substantial existing machinery to the actual
competition objective and evaluating it across all problems and versions.
Today the router preferentially selects the shortest checked source, while
the Arena also rewards low elaboration cost and cross-version compatibility.

Three distinct success claims must stay separate:

1. **Engineering progress:** more supported proof shapes, fewer wasted compiler
   calls, reproducible receipts, or improved failure handling.
2. **Measured optimization progress:** a higher local Arena-compatible score
   under matched resources, with measurement limitations stated.
3. **Competition success:** an organizer-scored, eligible submission that beats
   the relevant leaderboard entry. No current evidence establishes this.

There is no responsible guarantee of winning. The plan below maximizes our
ability to discover, measure, and retain genuine improvements.

## 2. What the competition actually rewards

### Current rules and corpus

The current organizer source announces 50 full-benchmark problems, release on
November 1, 2026, and submission deadline November 8. The closed track caps API
spend at US$3 **per problem**, not merely on average. The open track permits
at most four 80 GB A100s and 48 hours end-to-end. All model calls, including
retries and discarded candidates, must be accounted for at public list prices.
The code and pinned reproduction instructions accompany a 3–9-page technical
report submitted through OpenReview, with Approach, Models, Budget accounting,
and Reproduction sections. Recheck these requirements before submission.
[Organizer rules source](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/blob/main/app.py).

The local corpus contains **15 warm-up problems**, three each from Strata,
PhysLib, CSLib, ArkLib, and PutnamBench, with **36 listed problem/version
checks**. The vendored heartbeat file contains positive reference counts for
all 15. Copying the public repositories did not obtain an unreleased full
corpus or the separate evaluation worker.
[Local manifest](papers/completion/lean_refactor_arena/data/corpus_manifest.json),
[worker boundary](papers/completion/lean_refactor_arena/space/UPSTREAM_IMPORT.md).

I re-fetched `app.py`, `benchmark.py`, and `leaderboard.py` over HTTPS during
this review; all three were byte-identical to the vendored Space snapshot
`6a1384b7e3127f5d556e727d5d53cc17b4acdb40`. These are current observations,
not a promise that the rules will remain unchanged.

### The objective, not our old proxy

For a valid default-toolchain compilation, the published leaderboard averages
length reduction, heartbeat reduction, and the fraction of listed versions
passed. Missing or invalid submissions contribute zero, and all problems
remain in the denominator. Negative reductions are possible. Missing/nonpositive
reference heartbeat denominators produce zero heartbeat reduction in the
current implementation. Match its rounding and default-version handling.
[Organizer scoring implementation](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/blob/main/leaderboard.py).

Ignoring implementation rounding, when both reference denominators are positive:

```text
L_i = 100 × (1 − candidate_tokens_i / reference_tokens_i)
H_i = 100 × (1 − candidate_heartbeats_i / reference_heartbeats_i)
C_i = 100 × passed_listed_versions_i / listed_versions_i
S_i = (L_i + H_i + C_i) / 3
S   = sum(S_i for every benchmark problem) / N
```

Consequences for our design, derived from that formula:

- An unchanged, valid proof with identical measured cost and 100% compatibility
  scores about 33.33. Keep it as a fallback; do not omit difficult problems.
- A 60% shorter proof with a 50% heartbeat increase and full compatibility
  scores 36.67. A 40% shorter proof with 60% lower heartbeats and full
  compatibility scores 66.67. Shortest-first can select the wrong proof.
- Losing one of three compatibility checks costs 11.11 points on that problem.
  All-version success is valuable, but treating it as an unconditional hard
  optimization gate is stricter than the published score. Keep a fully portable
  incumbent and evaluate the explicit trade-off rather than silently changing
  the objective.
- Every problem has equal weight. Optimize percentage gains, not total tokens
  removed from whichever long theorem happens to be easiest.
- Do not add expression-node counts, autoencoder loss, or wall time to the
  official formula. Track them separately as diagnostics or declared guardrails.

The old warm-up harness uses a **0.55 token / 0.45 elaboration ratio** proxy.
Keep that frozen protocol reproducible; introduce a separately named, versioned
Arena scoring mode rather than relabeling historical reports.

## 3. Starting point: reuse, evidence, and missing links

| Existing component | What we can reuse | Gap to close for the Arena |
| --- | --- | --- |
| `router_tuning.py`, `oracle.py`, `search.py` | Bounded candidate pools, compilation, composition, incumbent search | Select by measured score/Pareto frontier, not only source tokens; make resource costs explicit |
| `logic_refactor.py`, `catalogs.py`, `proof_slicing.py` | Existing reduction families, coarse-to-fine deletion, rotating sweeps | Measure coverage and marginal value on real project proofs; use native syntax/dependencies where available |
| `solver_feedback.py`, `typed_terms.py` | Position-bound solver suggestions and checked term replay | Multiline/branch-aware support, more version-tested suggestion forms, heartbeat-aware admission |
| `proof_state.py`, `proof_replay.py`, `lean/` | Native observation and closing-span replay; original-goal/type and axiom checks | Project-resident contexts, complete metaprogram state where necessary, coverage beyond small closed telescopes |
| `replay_router.py`, `llm_router.py`, `jev.py` | Injected generators, bounded anchored proposals, typed policy answers | Explicit Arena adapter with full identity/cost provenance; no implicit live calls |
| `proof_metrics.py`, `expr_dag.py`, `structural_training.py` | Term measurements, typed structures, guarded teachers | These are diagnostics/research policies, not an Arena scoring oracle |
| `rewrite_distillation.py`, `replay_distillation.py`, `structural_policy.py` | Verified-pair collection, sparse edit/readout training, frozen-checkpoint evaluation | Broader independent data; prove value beyond deterministic teachers and known motifs |
| `tactics.multi_armed_bandit` | Thompson, UCB1, epsilon-greedy; explicit pending action and observation | Bind rewards to verified score changes and exactly-once receipts; account for costs and changing incumbents |
| `proof_ca.py`, `plan.py`, `board.py`, `graph.py` | Typed cells, Horn-rule checking, dependency/evidence flow, scheduling | Harden receipt/resource/locality boundaries before making it the authoritative Arena coordinator |
| `kernel.py`, `memory.py`, `tape.py`, `stack.py`, `repair.py` | Cache, context windows, journals, work bookkeeping | Environment-complete cache keys, exact replay, ownership-aware acquisition, trustworthy counters |
| Arena `harness/`, `tools/`, `space/`, `upstream/` | Frozen data, version provisioning/adapters, organizer UI/scoring source, optimizer reference | A complete local evaluation/report path; full release ingestion; independent worker parity checks |

Do not import upstream LangGraph/LangChain as a second orchestrator. Extract
small licensed interfaces, schemas, strategy data, or baseline adapters where
useful. Keep heavyweight models and integrations optional; preserve current
endpoint restrictions and the distinction between a server owner and its HTTP
client. New runtime instances should receive explicit dependencies rather than
relying on mutable global hooks.

### What our existing results do and do not establish

- The saved `CallElimCorrect.substOldPostSubset` regression reports **482→391
  local body tokens**, including a later 392→391 improvement. Its stored receipt
  records a real pinned Lean recheck and an axiom audit. This review did not
  repeat that compilation.
- Critically, the organizer JSONL gives **313 reference tokens** for that same
  original theorem. Our punctuation tokenizer is not established as the worker's
  tokenizer. Do not divide 391 by 313, or call 482→391 an official reduction.
  [Regression artifact](tests/fixtures/kernel_refactor_local_best.json),
  [local tokenizer](jevops/proof_tokens.py).
- The guarded rewrite report records 8/8 shortened holdouts, but also unchanged
  Arena inputs, no semantic-family decontamination, and no checkpoint promotion.
  [Saved report](tests/fixtures/guarded_rewrite_report/summary.md).
- The structural-feature experiment reports 2/2 valid holdouts versus lexical
  1/2, on two same-family controls. This is useful machinery validation, not
  evidence of an Arena advantage or a trained graph encoder.
  [Saved report](tests/fixtures/structural_feature_report/summary.md).
- Native replay already exposes a case where shorter source increases the
  unique expression-node count. Source size, proof size, and elaboration cost
  must remain distinct. [Replay findings](PROOF_REPLAY.md).

These results justify extending the working paths, not claiming broad model
generalization or spending the whole competition budget on training.

## 4. Priority 0: make the evaluator and receipts trustworthy

This is the prerequisite for every algorithmic experiment.

### 4.1 One versioned evaluation contract

Create a thin Arena evaluator using `lean.py`, `proof_trust.py`, and existing
toolchain/project adapters. A candidate record should bind:

```text
problem + exact original statement/envelope + candidate source digest
project commit + transitive dependency manifest + Lean/Lake versions
imports/options + verifier/audit version + axiom/intake policy
tokenizer version + measurement method + reference metric identities
parent edit/attempt + generator/model/config identity + resource receipts
per-version outcome + diagnostics + actual metrics + cache provenance
```

Preserve exact statement prefixes and check the elaborated target/type where
supported. Locate the body using the known statement boundary or native syntax,
not the first `:= by` regex: statements can contain internal definitions.
Never verify against an environment that already offers the target theorem as
an assumption or reachable circular dependency. A zero exit code, empty goal
list, model confidence, or legacy `theorem_ok` flag alone is insufficient.

Mirror organizer intake checks, including forbidden metaprogramming and proof
shortcuts. Submission source must not contain our diagnostic commands. Run
instrumentation in a trusted wrapper. Distinguish the organizer's policy from
our stricter standard-axiom policy; inspect incompatible originals explicitly,
and never silently loosen trust to make a score pass. Preserve original imports
and options. No hidden helper declarations or altered theorem statements.

### 4.2 Establish metric parity before calling a number an Arena estimate

1. Reproduce all 15 published reference token counts. Inspect upstream
   `utils.proof_length`, but do not assume that optimizer code equals worker code.
   Test Unicode, qualified names, multi-character operators, nested comments,
   blank lines, term proofs, and internal `:=` boundaries.
2. Reproduce reference heartbeat measurement on the default pinned environment.
   Lean heartbeats are not elapsed milliseconds or pure kernel time. Record
   exact measurement scope, imports, options, toolchain, and any mismatch.
3. Evaluate each unchanged proof on all its listed project/version pins: a
   matrix of 36 checks for warm-up, not one installed Lean version for everything.
4. Differential-test score arithmetic against the vendored leaderboard on
   complete, missing, failed, negative-reduction, and absent-metric fixtures.
   Unknown compatibility is **unknown**, not the source's empty-map 100% fallback.
5. Once explicitly authorized, compare a small diagnostic submission with the
   organizer's returned measurements. Until parity is established, label our
   score a local estimate and include the unmatched dimensions.

The public UI is not the evaluator. Full worker parity may require organizer
clarification or returned receipts; do not invent missing behavior.

### 4.3 Readiness, resources, and failure semantics

- Split readiness into `schema_valid`, `provenance_verified`,
  `dependencies_present`, `baseline_compiles`, and `metrics_calibrated`. The
  current corpus check only establishes data readiness, not executable readiness.
- Reject empty corpora. More than 15 rows does not authenticate the full release.
  Freeze release provenance, hashes, count, names, and version pins in a new
  manifest; retain the warm-up fixture unchanged.
- Use integer operation units and integer currency subunits; reserve worst-case
  authorized work before calls, then reconcile actual usage. Zero must remain
  zero. Record all retries, discarded candidates, ranking and embedding calls.
- Keep API dollars, compiler calls/CPU time, GPU time, and wall-clock deadlines
  as separate constraints. A subscription-backed interface is not automatically
  a zero-cost competition model. Unknown billing is a compliance gap.
- Record parse/type failures, trust rejection, timeout, infrastructure failure,
  unsupported feature, and valid-but-worse result separately. Retry transient
  failures only within an explicit cap; never call them disproved propositions.
- Use disposable project workspaces/process isolation and resource limits for
  candidate checking. Lean metaprograms can execute code; a kernel audit does
  not provide an OS sandbox. Do not expose credentials to compiler subprocesses.

**Exit gate:** a reproducible baseline table for every problem/version, a tested
score implementation, correct accounting, and an explicit list of remaining
worker mismatches. Missing toolchains are visible gaps, not successful checks.

## 5. The research-backed optimization portfolio

The literature motivates these experiments; it does not predict JevOps' gains.
The implementation proposals below are engineering inferences, not capabilities
claimed by the cited papers or promised percentage improvements.

### A. Structural shrinking and dependency slicing — first algorithmic priority

**Research:** Delta debugging and hierarchical delta debugging reduce structured
inputs using an oracle, with coarse-to-fine exploration instead of arbitrary
flat deletion. We adapt the acceptance predicate to “still proves the same
theorem and improves the measured objective.”
[Zeller–Hildebrandt](https://www.st.cs.uni-saarland.de/papers/tse2002/),
[Misherghi–Su](https://www.cs.ucdavis.edu/~su/publications/icse06-hdd.pdf).

Extend `proof_slicing.py` using Lean syntax/InfoTree spans:

- Delete unused `have` blocks, redundant local aliases, unnecessary tactic
  siblings, repeated normalization, and unused solver premises.
- Search whole proof, induction/case branch, block, tactic, then argument list.
  Maintain binder/dependency information to avoid obvious dangling references.
- Minimize `simp only` and arithmetic support sets with independent rechecks;
  removal can change elaboration and subsequent goals, so dependencies are a
  filter, not a substitute for the compiler.
- Memoize exact candidate/environment checks. Compose nonoverlapping edits,
  then check the composition again; individually valid edits can interact.
- Preserve score-improving longer outputs when their heartbeat savings justify
  them. Only claim local deletion-minimality if an exhaustive final sweep
  actually completed; bounded search is not a global minimum.

**Experiment:** current slicer versus syntax-aware slicing, with the same
candidate/compiler budget. Measure valid proposals, unique checks, score gain,
and attempts per retained improvement. Likely broad coverage; actual benefit
must be measured by family.

### B. Discover with automation; replay a smaller explicit explanation

**Research/tool support:** Aesop performs white-box best-first proof search and
can suggest explicit scripts. Lean's `grind?` can provide restricted theorem
sets or scripts for replay. Explicit output can avoid repeating expensive search,
but its cost must still be measured.
[Aesop paper](https://zenodo.org/records/7430233),
[Aesop implementation](https://github.com/leanprover-community/aesop),
[Lean grind documentation](https://lean-lang.org/doc/reference/latest/The--grind--tactic/Minimizing--grind--calls/).

Extend `solver_feedback.py` and `typed_terms.py` rather than adding a new hammer:

1. Profile expensive original proof spans where the pinned version supports it.
2. Try definitionally simple closers (`rfl`, hypothesis reuse, direct lemma
   application), then scoped `simp?`, `aesop?`, `grind?`, or term recovery where
   supported by that exact project/version.
3. Replay suggested terms/scripts with minimized premises and explicit
   instantiations. Attribute every suggestion to its exact source and span.
4. Measure both the explicit result and the compact automation call. Large
   generated terms can lose on length, elaboration, or version compatibility.
5. Keep the best score frontier, not a universal “explicit terms are better” rule.

Start with multiline suggestions and closing branches, which are currently
restricted. Do not assume every tactic has a usable `?` variant on older pins.
Do not use `native_decide` or similar forbidden shortcuts to win a length metric.

**Experiment:** original automation, current single-line harvesting, and extended
replay, under identical budgets. Primary measure: heartbeat and combined-score
change; secondary: source/term sizes and version failures.

### C. Goal-local resynthesis with checked subproof replacement

**Research:** LeanTree studies factorized proof states; Lean Copilot combines
model proposals with interactive proof search; HTPS models proof search using
AND/OR structure. These support local, dependency-aware search rather than
repeatedly rewriting entire long proofs.
[LeanTree](https://arxiv.org/abs/2507.14722),
[Lean Copilot](https://arxiv.org/abs/2404.12534),
[HyperTree Proof Search](https://arxiv.org/abs/2205.11491).

Use the existing `proof_state.py` → `proof_replay.py` → whole-source checker path:

- Select a costly or verbose closing region. Supply only the target, required
  local telescope, accessible premise signatures, version, and bounded context.
- Let deterministic tactics and an injected model propose competing replacements.
  Check original goal assignments in the original environment, then splice and
  independently verify the complete theorem.
- Prioritize adding **project-resident capture/replay**: realistic namespaces,
  imports, local instances, declarations, and Unicode source spans. Current
  closed-telescope controls do not establish this coverage.
- Never split goals that share unresolved metavariables as independent cells.
  Use a joint state or abstain; textual goal similarity is not state identity.
- Retain the original subproof as fallback. Initially use bounded best-first
  search; only add MCTS/HTPS machinery if simple search demonstrably saturates.
- General open-state replay is later work: it needs full state/assignment and
  dependency integrity, not plausible reconstruction from observation JSON.

**Experiment:** whole-proof proposals versus anchored subproof proposals, matched
model and spend. Report supported-span coverage, local success, whole-proof
survival, final score, prompt tokens, and all failed attempts.

### D. Retrieve applicable lemmas and version-tested refactoring patterns

**Research:** LeanDojo/ReProver emphasizes accessible-premise retrieval. Lean
Refactor uses version- and cost-annotated strategy retrieval for proof
optimization. Adopt those ideas inside JevOps, without copying an entire agent
stack or assuming a paper's benchmark gains transfer here.
[LeanDojo](https://arxiv.org/abs/2306.15626),
[Lean Refactor, v2](https://arxiv.org/html/2605.20244v2).

Build two separate indexes:

- **Premises:** declarations accessible at the original theorem location, with
  types, namespace, imports, dependency identity, and version availability.
- **Strategies:** verified before/after edits with applicability features,
  measured metric deltas, supported environments, costs, and failed examples.

Start with symbol/type-head/operation overlap and inexpensive text retrieval.
Then test existing structural features or an optional embedding reranker. Filter
by accessibility before ranking. Never retrieve the target itself, a circular
descendant, or a leaked evaluation solution as an admissible premise.
Similarity proposes a candidate; Lean checks it. Validate any upstream data's
license, availability, provenance, overlap, and version metadata before import.

**Experiment:** no retrieval, random retrieval, lexical retrieval, version-aware
retrieval, then structural/embedding reranking. Keep prompts and paid budgets
matched; inspect stale-premise errors and score gain per call.

### E. Cost-aware portfolio search with the existing bandit

**Research:** UCB-style bandits formalize exploration versus exploitation;
Hyperband motivates staged resource allocation. Their guarantees do not directly
apply to our changing incumbents, correlated rewrites, and censored timeouts.
Treat this as an empirical scheduling adaptation.
[Auer–Cesa-Bianchi–Fischer](https://doi.org/10.1023/A%3A1013689704352),
[Hyperband](https://www.jmlr.org/papers/v18/16-558.html).

Use tactic families as arms: slicing, premise minimization, explicit replay,
local resynthesis, retrieved rewrite, existing specialized certificates, and
larger model proposals. Features include proof shape, corpus, version, failure
type, expensive tactics, incumbent metrics, and remaining resources.

- Begin with round-robin and existing UCB1 as interpretable baselines. Use
  contextual policies only after collecting enough independent observations.
- Maintain a verified Pareto frontier for length, heartbeats, compatibility,
  with optional declared engineering guards. A dominated candidate need not be
  submitted, but may remain a bounded search intermediate.
- Attribute marginal score gain to a unique attempt and its parent incumbent.
  For the existing `[0,1]` reward API, a starting proposal is clipped positive
  `delta_problem_score / 100`; retain the unclipped raw metrics in receipts.
  Track success probability and improvement magnitude separately if using
  Thompson sampling; fractional Beta updates are a heuristic, not calibrated
  Bernoulli inference.
- Keep CPU/API cost models separate. Predict gain per scarce resource, and
  compare resulting policies rather than mixing dollars and milliseconds in an
  arbitrary denominator. Count failures and uneventful attempts.
- Deduplicate observations by attempt/receipt identity. A cache hit or replay
  must not create another win or charge. A pending pull needs explicit completion
  or cancellation after infrastructure failure.
- Reserve exploration and periodic FIFO service. Bounded budgets cannot promise
  closure, but low model priority must not permanently erase useful enabled work.
- Stage cheap default checks before costly version sweeps, while reserving
  final evaluation capacity. Timeouts are censored observations, not semantic
  failures; do not systematically prune every expensive tactic too early.

**Experiment:** round-robin, random, UCB1, and cost-aware contextual selection
over the same arms. Compare score-versus-resource curves and final per-problem
deltas at equal compiler budgets and, separately, equal paid budgets.

### F. Bounded search beyond greedy shrinking

**Research:** Stochastic superoptimization explores beyond a single greedy
rewrite path. Equality saturation compactly retains equivalent alternatives;
small-proof extraction studies the size of explanations, not just expressions.
[STOKE](https://arxiv.org/abs/1211.0557),
[egg](https://arxiv.org/abs/2004.03082),
[Small Proofs from Congruence Closure](https://arxiv.org/abs/2209.03398).

Our adaptation: retain a small diverse beam of checked candidates and bounded
neutral/temporarily worse intermediates, while keeping the best submission
incumbent monotonic in score. Try atomic multi-edit replacements and controlled
restarts. Measure whether the extra exploration actually pays for itself.

Reuse the Boolean e-graph, constructive propositional proofs, Farkas certificates,
and difference-bound reductions **only in their supported domains**. First count
how many benchmark regions fit those domains. Do not spend a week improving an
oracle that applies to none of the current problems.

General dependent Lean equality saturation is a separate high-risk project:
binders, universes, substitution, type dependencies, and proof reconstruction
must be preserved. Defer it until the cheaper portfolio plateaus. Relevant
research identifies these issues rather than solving them by treating Lean
expressions as untyped strings.
[Lean expressions in e-graphs](https://arxiv.org/abs/2405.10188),
[Slotted E-Graphs](https://goens.org/publications/schneider_pldi25/).

### G. Distill successful search only after proving the teacher's value

**Research:** ProofOptimizer uses Lean-verified simplification to supply expert
iteration and reinforcement-learning training signals. It motivates verified
self-improvement; it does not establish that JevOps' small sparse editor will
match a large trained model.
[ProofOptimizer](https://arxiv.org/abs/2510.15700).

Extend existing distillation rather than starting with full-model RL:

1. Collect score-improving teacher edits and hard negatives from training-only
   proofs, including valid but slower, version-fragile, and unsupported edits.
2. Preserve source/goal/environment identities, measured deltas, costs, and
   teacher provenance. Synthetic reverse edits are separate augmentation,
   not independent discoveries or evidence of held-out generalization.
3. Train the current sparse selector/reranker first. Compare with its teachers,
   a frequency table, lexical features, and independently trained graph-feature
   ablations. Only then consider parameter-efficient larger-model tuning.
4. Freeze vocabulary, tokenizer, grammar, checkpoint, and split before evaluation.
   Report raw model-only predictions before any repair or fallback.
5. Separate **candidate admission** from **model promotion**. A fully checked
   score improvement is useful even if reconstruction CE worsens. Conversely,
   lower CE or better cosine cannot admit an invalid proof.
6. Keep the existing expression-nongrowth research protocol intact. Define an
   explicitly separate Arena policy if measured score, rather than source-plus-
   DAG nongrowth, is the objective. Do not relax old gates retroactively.

**Promotion gate:** the frozen student saves search resources at matched final
score, or improves held-out score at matched resources, without weakening
correctness or accounting. Otherwise retain the deterministic teacher.

## 6. How the neurosymbolic cells should help, concretely

This is orchestration of real checked inference and evidence, not a second Lean
kernel or an assertion that neural activation proves a theorem.

Use `proof_ca.py` for finite candidate rounds with explicit cells for candidates,
version obligations, rewrite regions, accepted receipts, and rule applications.
For example, fixed ground-rule instances can derive operational eligibility:

```text
ArtifactBound(c,e), StatementPreserved(c,e), IntakeAccepted(c,e),
DefaultLeanAccepted(c,e), AxiomPolicyAccepted(c,e)
    -> EligibleCandidate(c,e)

Version1Accepted(c,e), Version2Accepted(c,e), Version3Accepted(c,e)
    -> FullyPortable(c,e)

EligibleCandidate(c,e), MetricsBound(c,e), CompatibilityMeasured(c,e)
    -> MeasuredCandidate(c,e)
```

The checker admits input facts only from applicable adapter receipts. All
premises are required; neural priorities are not votes for missing evidence.
Partial compatibility remains measurable without deriving `FullyPortable`.
Metric values remain observations used by deterministic scoring, not logical
proofs of optimality. Candidate changes create new identities; do not overwrite
old receipts. Start a new declared finite round/epoch when extending the atom
universe; do not introduce fresh symbols secretly into a fixed Horn epoch.

Shared policy observations should contain bounded typed neighborhoods, with
explicit retrieval for remote context. Maintain complete logical dependency
sets even when the policy view is summarized. When a receipt arrives, notify
only affected rule applications and candidates. Use Jev for uncertain ordering
through an injected adapter; retain complete answer/model provenance and a
deterministic no-model policy. Neither sees an unrestricted mutable runtime.

### Required hardening before using this as the authoritative coordinator

Code inspection found concrete issues worth addressing, not merely a request
for more rankers:

- `_set_pending_counts()` currently visits every cell. Count that work and
  replace it with local pending-message accounting before claiming locality.
- Resources are reserved in `step()`, while directly calling `checked_apply()`
  can execute work outside that reservation. Put all effectful paths behind the
  same reservation/admission boundary.
- Bind logical contexts to canonical rule/fact content and immutable dependency
  records, not only caller-supplied revision strings.
- External receipt checks must bind the candidate artifact and relevant source/
  dependency identities, in addition to target, context, and verifier name.
- Recovery must retain operation/proposal idempotency, PRNG state, charges, and
  applicable evidence. Replaying observations cannot create fresh rewards.
- Verify byte limits and legitimate zero limits across kernel cache policies.
  Atomic file creation alone does not make stale-lock takeover and unconditional
  release ownership-safe. Remain single-owner until that protocol is tested.

Keep this work narrow and test-driven. If cellular scheduling does not improve
score-per-resource over a deterministic work queue, use the queue for the entry
and retain the evidence graph for audit. The framework should earn its overhead.

## 7. Evaluation design: learn what works without fooling ourselves

### Datasets and contamination

- **Warm-up:** all 15 publicly inspected problems are development/regression
  data now. Do not relabel them blind holdouts.
- **Auxiliary development corpus:** proposed initial target of 100–200 pinned
  non-Arena proofs across the five source styles, selected by a recorded rule
  before running methods. This is a collection target, not data already held.
- **Held-out evaluation:** split by declaration family/file/dependency cluster,
  not random renamed snippets. Detect exact and normalized-statement duplicates,
  shared generated parents, and substantial near-duplicates. Publish unresolved
  leakage risks; similarity filtering is not a proof of decontamination.
- **Cross-corpus transfer:** leave one source family out where feasible; report
  each family separately. Three warm-up problems per family cannot establish
  robust statistical generalization.
- **Full release:** create a new provenance manifest and preserve a pre-release
  frozen system. If rules allow per-instance adaptation, record it separately
  from blind evaluation; never train on evaluation teachers while calling the
  resulting score zero-shot. Clarify organizer restrictions before using such
  adaptation in an entry.

### Baselines and ablations

| Arm | Purpose |
| --- | --- |
| Identity/original proof | Coverage, metric parity, fallback floor |
| Current deterministic JevOps | Honest existing-system baseline |
| Current router/portfolio, learning off | Separate search quality from student quality |
| + structural shrinking | Marginal value of dependency-aware deletion |
| + explicit solver replay | Marginal heartbeat/search-cost improvement |
| + local state search | Value of anchored goals versus whole-proof prompts |
| + version-aware retrieval | Value of applicable context, versus random/lexical controls |
| + bandit allocation | Adaptive scheduling versus fixed round-robin over identical actions |
| + frozen learned selector | Model-only value and end-to-end value, separately |
| Upstream Lean Refactor, if provisioned | External reference; use a separate optional environment and matched backbone/budget where possible |

Do not call comparisons matched if one method gets historical winners, more
compiler attempts, a different model, or extra retries. Evaluate historical seeds
as their own arm. In addition to incremental ablations, run leave-one-component-
out checks on the final system to expose interactions.

For controller-specific experiments, hold the same task set, action generator,
scoring interface, compiler/verifier behavior, and budgets fixed. Compare a
dependency FIFO queue, a genuine centralized frontier-scoring controller, and
local cellular scheduling with FIFO fairness. Instrument global scans; relabeling
the same policy/FIFO code is not a meaningful centralized baseline.

### Required metrics and decision rules

Report per problem and aggregate:

- Validity/default compile rate, trust/intake status, compatibility matrix.
- Reference/candidate tokens, heartbeats, all three score axes, combined score,
  and original fallback use; no best-case-only averages.
- Generated candidates, unique compile attempts, verifier calls, failures,
  timeouts, retries, cache hits, and independently measured checks.
- API usage/cost, CPU/GPU/wall time, peak memory where actually measured;
  startup/cold-cache and warm-cache results separately.
- Policy calls, cells visited, edges traversed, messages, and global work.
- Term-tree/DAG sizes as diagnostics, not surrogate competition scores.
- Search-only versus model-only output; accepted teachers versus student output;
  every checkpoint decision and its provenance.

Use at least three fixed search seeds for stochastic development comparisons,
subject to the declared experiment budget. Use paired per-problem deltas and
report all regressions; bootstrap intervals are descriptive with such a small
corpus. Do not select the best of several paid runs without counting their total
cost toward the applicable per-problem competition cap.

Practical go/no-go rule: retain a component only if it improves held-out score
at matched resources or reduces resources at matched quality, by a margin larger
than observed measurement variability. Set the minimum worthwhile margin after
baseline noise measurement but **before** inspecting the comparison. Neutral
results do not justify extra production complexity.

### Family-specific hypotheses to test, not assumed wins

| Source style | First investigations | Main risk |
| --- | --- | --- |
| Strata | Repeated induction branches, hypothesis transport, simplifier support, program-verification certificates where applicable | Deep project context; unrestricted logical abstraction changes the problem |
| CSLib | Structural induction, direct library-lemma reuse, branch-local synthesis | Namespaces, typeclasses, and changing APIs |
| ArkLib | Algebraic normalization, support minimization, expensive automation replay | Domain-specific lemmas, large proof terms, version fragility |
| PhysLib | Imported-lemma retrieval and replacing broad simplification/automation | Dependency-heavy contexts; not everything is arithmetic |
| PutnamBench | Proof skeleton reuse, local arithmetic/search, targeted larger-model rewrites | Global mathematical insight and brittle large search calls |

First collect proof-shape and hotspot statistics; source labels are only weak
priors and must not hard-disable useful tactics.

## 8. Delivery sequence and concrete tickets

Estimates below are planning ranges in focused engineer-days, not measured
throughput or guaranteed calendar commitments. Provisioning and model access
can dominate them. The critical path is evaluator → portfolio → measured
ablations → release-ready entry. Optional research must not block it.

| Order / ticket | Scope and existing code | Deliverable and acceptance gate | Estimate |
| --- | --- | --- | --- |
| P0-1: measurement parity | Arena harness/tools, `lean.py`, tokenizer adapters | All warm-up baselines and 36 version outcomes; differential score fixtures; unresolved worker differences explicit | 2–4 days |
| P0-2: trust/accounting | `proof_trust.py`, receipt adapter, `kernel.py` | Exact artifact/environment binding, no circular target, zero/exact budgets, idempotent charges, transient failure tests | 2–4 days |
| P1-1: score-aware incumbent | `router_tuning.py`, `oracle.py`, `refactor_report.py` | Versioned Arena objective, portable fallback, Pareto frontier; synthetic shorter-but-worse ranking regression | 1–3 days |
| P1-2: structural shrinking | `proof_slicing.py`, `logic_refactor.py`, native spans | Head-to-head test with current slicer, including dependent binders and edit composition | 2–4 days |
| P1-3: explicit replay | `solver_feedback.py`, `typed_terms.py`, `proof_replay.py` | Version-tested multiline/branch suggestions; measured heartbeat deltas; no diagnostic leakage into submissions | 2–4 days |
| P2-1: project-local state | `proof_state.py`, `proof_replay.py`, `lean/`, `replay_router.py` | Capture/replay real project spans, retain fallback; reject stale/shared-mvar states; whole-theorem verification | 4–8 days |
| P2-2: retrieval | Existing graph/search/catalog interfaces | Pinned accessible-premise and verified-strategy indexes; lexical/random/version-aware ablation | 3–5 days |
| P2-3: allocation and cells | `tactics.py`, `proof_ca.py`, `plan.py`, `kernel.py` | Exactly-once bandit feedback, resource-aware schedule, real local counters; FIFO/centralized/cellular comparison | 3–5 days |
| P3-1: distillation | Existing sparse training and replay runners | Decontaminated split manifest; raw student versus teacher/frequency baselines; explicit promotion decision | 3–6 days after data exists |
| P3-2: submission rehearsal | Arena tools/report packaging | Fresh-environment reproduction, complete JSONL, all usage receipts, pinned code/model artifacts and required report | 2–3 days |

**First five working days:** prioritize P0-1/P0-2 and a minimal P1-1 vertical
slice. End with the first defensible full warm-up baseline, not more unmeasured
tactic names. If toolchains are missing, complete the offline score/receipt
tests and list the exact missing pins while provisioning is handled separately.

**Suggested calendar:** September 22–30 for the measurement foundation;
October 1–14 for cheap portfolio improvements and initial local-state coverage;
October 15–24 for retrieval/allocation experiments and only justified training;
October 25–31 for freeze and fresh-environment rehearsal. November 1 creates
the official release epoch; finish budgeted generation and verification early
enough to leave November 6–7 for audit and submission before November 8.
Scope should shrink if the prerequisites slip, not the evidence standard.

### Track and budget strategy

Start with a model-free measured baseline; it is useful in either track. Treat
the closed track as an initial planning default only if reproducible API access
and complete usage/list-price accounting are available. Otherwise qualify the
open-track hardware before committing to it. Do not pretend a local GB10/NVFP4
development run is an A100 result or that a model format will transfer unchanged.

Within a problem's budget, make cheap deterministic passes first, then reserve
bounded paid exploration for unresolved high-opportunity regions. Use measured
pilot usage to choose caps, including output-token limits and retry reserves;
do not invent a model price or an optimal fixed number of calls. Every scoring,
embedding, judge, and generation model must be disclosed. The full benchmark's
announced size would imply at most $150 of counted closed-track API spend if
all 50 problems each use the full $3 cap; it does not authorize any spend here.

Open-track qualification needs measured throughput and end-to-end execution on
the permitted hardware. Include initialization, retrieval, generation, checking,
and retries in the timing definition required by the organizer. Clarify any
ambiguity about development/training versus final-run accounting in advance.

## 9. Explicitly defer or reject

- Another parallel agent framework, replacing JevOps with the upstream agent
  stack, or more ranking functions without a tested new transformation.
- Full distributed execution, an unvalidated trained NCA/GNN, and general
  dependent equality saturation on the competition critical path.
- Large-model RL before a cheap teacher portfolio, adequate data, and held-out
  marginal value exist.
- New global helper libraries, changed statements/imports, unsafe tactics,
  metric spoofing, or exploiting evaluation weaknesses. Reuse accessible lemmas
  and lawful local proof structure instead.
- Token-count-only promotion, CE/cosine as correctness, cached receipts as new
  independent checks, or treating timeout/absence as a counterexample.
- Claiming the full corpus is available, the local score is official, paper
  percentages are our expected gains, or a competition win is guaranteed.

## 10. Work actually performed for this plan

Read-only inspection covered the current kernel, scheduling/bandit interfaces,
router winner selection, slicing/solver/replay/training paths, Arena harness,
data, scoring/intake source, and saved result reports. Primary papers and
official documentation are linked at the relevant decisions above. No paid
inference, training, new Lean compilation, benchmark optimization, upload,
commit, or push was performed for this plan.

Executed:

```bash
python papers/completion/lean_refactor_arena/tools/check_corpus.py
python -m pytest -q tests/test_bandit_tactic.py tests/test_proof_tokens.py \
  tests/test_lean_refactor_corpus.py tests/test_lean_refactor_upstream.py \
  tests/test_proof_ca.py
```

Observed: the corpus checker returned the expected 15-row warm-up and frozen
hash, with `official_full_corpus: false`. The targeted tests reported **38
passed, 1 warning in 2.81s**. The warning came from an optional local
`ipfs_datasets_py` deprecated cache import. These tests validate selected existing
interfaces, not competition performance or all proposed invariants. No complete
repository suite was rerun for this documentation-only task.

The recommended next implementation is **P0-1 plus the smallest score-aware
incumbent path**: make the identity baseline, one deterministic edit, complete
receipts, and the three-axis report work end-to-end before broadening search.

## 11. Implementation follow-up: first evaluator slice

Implemented after the planning review, on 2026-09-22:

- `jevops.arena`: a separate reference-compatible token counter (15/15 published
  references agree), immutable verification contexts, typed receipt checks,
  integer call budgets, bounded terminal-receipt reuse, and three-axis arithmetic.
  Differential tests include the pinned leaderboard's aggregate rounding.
- `RouterTuningLoop`: opt-in `arena-v1` selection with an injected evaluator,
  incumbent preservation, and no model promotion. The default shortest-source
  mode and frozen `LRA/v1` proxy remain unchanged. No proposal calls are made
  when verification is unavailable or its call budget is exhausted.
- `python -m jevops.arena --calibrate`: JSON reference measurements plus an
  explicit 36-check **unmeasured** baseline matrix.
- `python -m jevops.arena_demo`: a deterministic proposer/mock-verifier example
  through the existing router. Synthetic heartbeat values demonstrate choosing
  a longer but cheaper proof; they are not measurements of those Lean tactics.
- The corpus checker now rejects an empty file instead of reporting it ready.

The saved Strata artifact recounts as 313→237 reference-compatible tokens;
its original 482→391 local-token fields are preserved. This did not recompile
the saved proof or measure its heartbeats.

This is **partial P0-1/P0-2 and the initial P1-1 path**, not completion of those
milestones. A real adapter must still establish target/type integrity and
heartbeat measurements inside the pinned projects, with environment/provenance
checks, isolation, and external cost accounting. Official worker parity, the
real 36-check baseline, Pareto search, and model promotion remain outstanding.

Validation performed for this implementation follow-up:

```bash
python -m jevops.arena --calibrate
python -m jevops.arena_demo
python papers/completion/lean_refactor_arena/tools/check_corpus.py
python -m pytest -q
python -m pytest -q tests/test_arena.py tests/test_lean_refactor_corpus.py
git diff --check
```

Observed: calibration matched **15/15** reference lengths and explicitly left
**36/36** version checks unmeasured. The demo exercised score-aware selection
with **26 mock-verifier calls and 12 cache hits**, with no model calls or Lean
compilations. Corpus validation retained the expected 15-row warm-up hash;
the official full corpus is not present.

The full suite reported **775 passed, 8 skipped, 1 warning in 835.12s**.
It was collected before the final three regression tests were added; a later
focused run on the final implementation reported **81 passed in 0.28s**.
The warning was the optional local `ipfs_datasets_py` deprecated cache import.
Existing native Lean regression tests ran in the full suite, but this is not
the pinned-project Arena baseline. `git diff --check` passed. No paid inference,
benchmark submission, commit, or push was performed.

## 12. Implementation follow-up: native verification and local calibration

The next P0 slice adds `jevops.arena_lean` and the trusted native
`jevops/lean/ArenaCheck.lean` instrumentation. It consumes explicit, read-only
project bindings, exact Lean/project pins and dependency fingerprints. No clone,
checkout, build, installation, provider call or benchmark submission is implicit.
The frozen Lake admission path remains unchanged. This adapter is a separate
opt-in measurement mode for the existing evaluator, not a replacement agent.

The native checker rejects a target already present in the prefix environment,
elaborates reference and candidate in independent environment branches, checks
their actual target names and structural types (including section parameters
and universe parameters), and reports transitive axioms and raw heartbeat deltas.
Standard-axiom admission remains explicit. Missing imports and resource failures
do not become theorem counterexamples. A native measurement context must first
be calibrated using this method; published heartbeat denominators are not mixed
in. Reference drift remains inconclusive rather than producing a promotion.

`ArenaEvaluator` now preserves bounded canonical observations and supports
explicit live-context validation before cache reuse. Without such a validator,
`local_lean` mode does not reuse receipts. The native helper supplies pre/post
dependency checks, bounds subprocess IO/time and invocation counts, and strips
ambient credentials/search paths from the subprocess environment.

Actual local checks on the dependency-free smoke theorem verified a reduction
from **9 to 3 reference-compatible tokens** and **6 to 3 local command heartbeats**
on Lean 4.26.0. Both target/type and standard-axiom checks passed. These are toy
measurements, **not an Arena performance gain or official score**. The native
tests also exercise installed Lean 4.34.0 and a temporary pinned Git project;
the latter verifies that source bytes and the worktree remain unchanged.

Observed corpus readiness: all **36** rows remain `UNAVAILABLE` without explicit
prepared project bindings. The default harness project cache is absent. Required
tags **v4.25.0**, **v4.28.0**, and **v4.33.0-rc2** are also not installed. The
baseline command with a 36-invocation cap therefore executed **zero** native
processes and emitted a null score; it did not mislabel missing infrastructure
as failed proofs. The frozen corpus SHA-256 is unchanged.

Runnable commands and the project-manifest/API contract are documented in
[ARENA_NATIVE_VERIFIER.md](ARENA_NATIVE_VERIFIER.md). OS isolation, dependency
provisioning (including file-less Putnam bindings), actual 36-check corpus
measurements, organizer heartbeat parity and measured optimization experiments
remain outstanding. Before/after fingerprints require stable single-owner
inputs and are not transactional snapshots; this is trusted local execution,
not a sandbox for hostile metaprograms.

Validation commands and observed results for this follow-up:

```bash
python -m pytest -q --test-seal=off
# 855 passed, 25 skipped, 1 warning in 879.70s

python -m pytest -q --test-seal=off tests/test_arena.py tests/test_arena_lean.py tests/test_lean_refactor_corpus.py
# 121 passed, 18 skipped in 0.45s (native checks intentionally not enabled)

JEVOPS_ARENA_NATIVE_TESTS=1 python -m pytest -q --test-seal=off tests/test_arena_lean.py --tb=short
# 58 passed in 27.36s (includes installed-Lean and local pinned-Git tests)

python -m jevops.arena_lean --smoke --max-processes 2
python -m jevops.arena_lean --baseline --max-processes 36
git diff --check
```

The full run collected before the final three regression additions; the focused
runs cover the final implementation and those additions. Test-result reuse was
disabled for these commands. The full-suite warning is the existing optional
`ipfs_datasets_py` deprecated cache import. The smoke returned verified native
evidence; the corpus baseline returned 36 unavailable rows, zero executions,
and no score. `git diff --check` passed. No paid inference, downloads, benchmark
submissions, shared-project edits, JevOps commits, or pushes were performed.
The pinned-project integration test creates its own temporary Git fixture commit.

## 13. Implemented follow-up: pinned corpus environments and real baselines

This slice extends the same `ArenaEvaluator` / `NativeLeanVerifier` path; it
does not introduce a controller or invoke a model. In addition to explicit
project manifests, `--state-root` now inventories the existing harness layout
at a supplied path. An older prepared cache was found at
`/home/barberb/.local/state/ipfs_accelerate_py/vericodegen-2026-lra/track1-lake`.
The default cache's absence in section 12 did **not** mean there were no usable
projects anywhere. Discovery does not search the home directory or change HEADs.

Implementation changes:

- `jevops/arena_lean.py`: immutable Lake dependency records, exact Git/cleanliness
  checks, manifest-derived search roots, file-less Putnam binding, explicit cache
  inventory, a shared per-run fingerprint cache, and non-overwriting JSON report
  output. Lockfile versions 1.1.0/1.2.0 and escaped package names are supported;
  floating/path dependencies and directory escapes are rejected. Git inventory
  disables optional index writes. Intake/axiom/serialization/fingerprint code is
  included in the native boundary identity as well as the driver and adapter.
- `jevops/lean.py` and `harness/bake_oleans.py`: supplied Putnam Mathlib revisions
  reach the generated Lake requirement. Tag-only callers remain compatible. The
  organizer's vendored schema confirms that the JSONL hashes identify Mathlib4,
  not PutnamBench. Existing cached projects are not rewritten or rebaked.
- `jevops/arena.py`: fixes an actual corpus intake false rejection. ArkLib uses
  `#(...)` cardinality notation; treating every hash character as a forbidden
  command rejected an unchanged reference before Lean ran. Diagnostic commands
  remain blocked, and all 15 frozen references now have intake regression
  coverage. Intake success alone is never proof.
- `tests/test_arena_projects.py` and additions to `tests/test_arena.py`: offline
  tampering, stale-context, revision/header identity, compiled-artifact changes,
  cache inventory, renderer compatibility, zero-budget and report-preservation
  tests. Dependency fixture oleans are explicitly fake and never executed.
- `ARENA_NATIVE_VERIFIER.md`, README and the Putnam harness README document
  exact bindings, runnable commands, compatibility changes and the trust limits.

Readiness resolves **15 distinct environment jobs / 36 version checks**. In the
existing cache, 12 checks are eligible for native execution. The other 24 have
explicit gaps: 12 revision mismatches, 7 missing-toolchain rows, 3 Putnam rows
missing compiled Mathlib imports, and 2 absent Putnam project rows. The absent
required toolchains are v4.25.0, v4.28.0 and v4.33.0-rc2. A correctly pinned source
checkout is not itself a complete compiled environment. Putnam's adapter has
offline binding coverage, not a successful native Mathlib run in this pass.

The first real baseline exposed the cardinality intake bug: 11 references were
verified, one was rejected at intake without a Lean invocation, and 24 remained
unavailable. That rejection was not a counterexample to the reference. It led
to the specific regression/fix above and a fresh run under a new boundary
identity. Historical JSON reports were retained, not overwritten.

The corrected run verified **12/36 required version checks**, with 24 unavailable
and no remaining rejected/error/timeout rows. It used 12 native invocations and
zero model calls. All four source checkouts retained their original commits and
clean tracked state after the run.

| Source family | Available pin tested | Verified unchanged references |
| --- | --- | ---: |
| Strata | v4.26.0 | 3 |
| Physlib | v4.32.0 | 3 |
| Cslib | v4.31.0 | 3 |
| ArkLib | v4.31.0 | 3 |

The [persistent evidence summary](papers/completion/lean_refactor_arena/evidence/native-baseline-2026-09-22.json)
contains all 36 outcomes, per-check receipts and identity hashes. The complete
local report is `/tmp/jevops-arena-pinned-baseline-EUp5Yk/final-baseline.json`
(SHA-256 `548f291560671f7bb7616efb1687cc41e306adf8038a4b31978880d47b94f2f5`).
The summary is historical evidence, not an independently replayable proof
certificate or a reason to skip applicability checks in a new context. Its
bookkeeping regression binds each measured source hash to the frozen reference.

Preparation scanned 165,398 distinct fingerprint files, with 1,410,673 stat-cache
hits across repeated applicability checks. These are file-hash operations, not
additional verifications, and are separate from the native invocation budget.
No compiled dependency rebuild/source-to-binary reproducibility is claimed.
All scores remain null: this establishes usable baselines, not improved proofs,
full cross-version compatibility, or an official Arena result.

Validation for this slice (test-seal reuse disabled):

```bash
python -m pytest -q --test-seal=off tests/test_arena.py tests/test_arena_lean.py tests/test_arena_projects.py tests/test_lean_refactor_corpus.py tests/test_lean_refactor_upstream.py tests/test_kernel_boundary.py papers/completion/lean_refactor_arena/harness/test_splice.py
# 216 passed, 18 skipped, 1 warning, 87 subtests passed in 6.50s

JEVOPS_ARENA_NATIVE_TESTS=1 python -m pytest -q --test-seal=off tests/test_arena_lean.py tests/test_arena_projects.py --tb=short
# 94 passed in 30.51s; includes 18 actual installed-Lean integration cases

python papers/completion/lean_refactor_arena/harness/bake_oleans.py --self-check
# Passed; synthetic materialization/cache checks, no Lake build or proof claim.

python -m jevops.arena_lean --readiness \
  --state-root /home/barberb/.local/state/ipfs_accelerate_py/vericodegen-2026-lra/track1-lake

python -m jevops.arena_lean --baseline \
  --state-root /home/barberb/.local/state/ipfs_accelerate_py/vericodegen-2026-lra/track1-lake \
  --max-processes 12 --timeout 90 --output /tmp/jevops-arena-pinned-baseline-EUp5Yk/final-baseline.json
```

The warning is the existing optional `ipfs_datasets_py` deprecated cache import.
The complete repository suite was not rerun for this slice; the earlier full
run in section 12 remains historical, not evidence about every later edit.
No downloads, dependency builds, paid inference, automatic code-improvement
loop, submission, JevOps commit or push was performed. Temporary Git commits
are confined to offline test fixtures.

Before claiming optimization gains, finish the missing environments and run
controlled candidate trials. Same-source reference/candidate heartbeat counts
already show branch/cache differences; these are not refactoring improvements.
Repeated controls, organizer metric calibration, and full required-version
coverage still matter. The corpus remains the 15-problem warm-up subset; the
vendored organizer documentation says the full benchmark is not yet released.

## 14. Implemented follow-up: order-balanced candidate measurements

`jevops.arena_trial` now exercises fixed drafts through the existing evaluator
and native verifier with repeated unchanged controls. It reuses existing tactic
transforms and the proof slicer; it is not another agent framework, trained
policy, optimizer or admission bypass. `ArenaCheck.lean` can execute either
reference-first or candidate-first while starting both branches from the same
target-free prefix. The order is explicit in immutable verifier options and
checked against each native report. Default adapter behavior remains
reference-first, and the separate score-aware router still requires calibration.

For every required pin, the fixed schedule runs every arm in both orders for
every repetition. Within-block scheduling is randomized with a recorded seed.
Receipt caching is disabled; exact duplicate requests still incur fresh native
invocations and have separate sample identities. Code/dependency checks remain
active. Missing pins, unsuccessful controls and incomplete repetitions prevent
a full-coverage improvement claim. Shorter/slower and longer/faster arms remain
measured tradeoffs, not automatically rejected propositions. Raw distributions,
paired differences, per-order ranges and medians are retained. The descriptive
range/separation rule is not a significance test or a success probability.

### Observed pilot, not an Arena score

The controlled run on **CallElimCorrect.substOldPostSubset** used its entire
required version set (one pin: Strata v4.26.0 at
`451e5f047bafa010d178856db76c00029bfa4d7f`). It compared the unchanged proof, an
explicit historical regression seed, and the existing deterministic
`drop_redundant_simp_at` transform. All **12 fresh native invocations verified**:
three arms, two orders, two repetitions. No result cache was counted as a trial.

| Arm | Source tokens | Median raw heartbeats, reference-first | Median raw heartbeats, candidate-first |
| --- | ---: | ---: | ---: |
| Unchanged control | 313 | 5,206,000 | 5,206,006 |
| Historical regression seed | 237 | 5,118,456 | 5,118,476.5 |
| Existing simplification transform | 289 | 5,195,729 | 5,195,745 |

The seed is **24.28% shorter**, with approximately **1.68% fewer observed raw
heartbeats** in both orders. The transform is **7.67% shorter**, with approximately
**0.20% fewer observed raw heartbeats** in both orders. Differences exceeded the
observed control/candidate ranges in this small pilot. This does not establish
statistical significance, generalization, end-to-end latency gains, a new proof
discovery, global minimality or a corpus-wide result. The historical seed was
already known; the transform was already implemented. Their measured reductions
are new controlled observations, not evidence of learned dynamics. No code or
model was automatically promoted; all official/combined-score fields are null.

The [full persistent trial report](papers/completion/lean_refactor_arena/evidence/native-controlled-strata-2026-09-22.json)
includes the sources, fixed schedule, immutable contexts and all twelve receipts.
The original local report is
`/tmp/jevops-arena-controlled-VndGJr/strata-trial.json`, SHA-256
`4f0cba9fc50a0990e765b3a799b10a37b9b2d93448e5a655851f3f7b3849a29b`.
Its bookkeeping test reconstructs sample request identities; that test is not
another native proof event. Preparation read 8,884 fingerprint files and reused
328,708 stat-cache entries, separately from twelve verifier processes. The
shared Strata checkout stayed clean at its original revision.

### Environment preparation remains separate

No older compiled `oleans` snapshots were present in this prepared state root.
A read-only Git-object inventory did find **all twelve distinct repository
revision objects** locally, so those source revisions need not be fetched again.
Cslib v4.32.0 also declares the same Mathlib commit as the prepared Physlib
v4.32.0 environment (`81a5d257c8e410db227a6665ed08f64fea08e997`). That is a potential
reuse opportunity, not proof that every transitive dependency/build is ready.

The practical preparation order is isolated Strata v4.27.0/v4.29.1 projects
(neither lockfile requires Mathlib), then Cslib v4.32.0 after checking all shared
dependency pins. Do not change the existing shared checkouts or blindly attach
a nearby Mathlib build. The other missing toolchains and Putnam imports still
need preparation. This pass did **not** reduce the 24 unavailable matrix rows,
download packages, start builds, use APIs, restart the autoresearch loop, submit
to the organizer, or commit/push JevOps.

Commands, protocol, budgets and limitations are in
[ARENA_CONTROLLED_TRIALS.md](ARENA_CONTROLLED_TRIALS.md). Core fixtures are offline
and report zero actual native processes. Native integration tests now exercise
both branch orders, including wrong types, missing/circular targets, section
parameters and missing imports. Full-suite results from earlier sections remain
historical; this slice uses the focused regression and opt-in native commands.

```bash
python -m jevops.arena_trial --run \
  --problem CallElimCorrect.substOldPostSubset \
  --state-root /home/barberb/.local/state/ipfs_accelerate_py/vericodegen-2026-lra/track1-lake \
  --seed-candidate tests/fixtures/kernel_refactor_local_best.json \
  --strategy drop_redundant_simp_at --proposal-cap 1 \
  --repetitions 2 --seed 17 --max-calls 12 --timeout 90 --progress \
  --output /tmp/jevops-arena-controlled-VndGJr/strata-trial.json

python -m pytest -q --test-seal=off tests/test_arena.py tests/test_arena_lean.py tests/test_arena_projects.py tests/test_arena_trial.py tests/test_router_tuning.py tests/test_proof_slicing.py tests/test_lean_refactor_corpus.py tests/test_kernel_boundary.py
# 234 passed, 34 skipped in 59.07s (native integration intentionally disabled)

JEVOPS_ARENA_NATIVE_TESTS=1 python -m pytest -q --test-seal=off tests/test_arena_lean.py --tb=short
# 75 passed in 45.33s (34 installed-Lean integration cases, 41 offline cases)
```

## 15. Implemented follow-up: bounded isolated provisioning

The user authorized downloads, one isolated build at a time, and a **50 GB
decimal** allowance. `jevops.arena_prepare` implements a fixed-capacity FUSE
build volume, a read-only-root Docker runner, explicit read-only input mounts,
an OS-held single-build lock and a fixed container name. It does not promote
builds to proofs or use credentials/API inference. See
[preparation commands and recovery](ARENA_PREPARATION.md).

The current workspace is
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM`.
Its sparse image is 49,799,999,488 bytes; 200 MB is reserved for setup and
metadata. The payload cap is filesystem-enforced, while the small external
metadata reservation is headroom rather than a host-wide quota. A separate
32 MiB probe actually stopped with ENOSPC at 27,918,336 payload bytes. Docker
uses an existing image, disables persistent container logs and image pulls,
and confines downloads, extraction, builds, HOME and temporary data to the
volume. No shared checkout or global toolchain was rewritten.

Completed preparation, in serial order:

| Environment | Exact commit | Work | Observed wall time |
| --- | --- | --- | ---: |
| Strata v4.27.0 | `4348c65a93a3b57b1a4541991ed2d2fcdd9fa35d` | Pinned Plausible download; target dependencies built | 118.125 s |
| Strata v4.29.1 | `384e22374e0872095ad9c6f74c5998c09cfd93a9` | Pinned dependencies downloaded; target dependencies built | 75.327 s |
| Cslib v4.32.0 | `197a7be621263b84c67ca4f803f69205b36d06df` | Independent copy of all 9 matching Physlib dependency packages | 265.697 s |
| Cslib v4.32.0 | same | Project-specific dependencies built offline | 142.494 s |

Cslib's 1,694 reported Lake jobs include cached work: only **28** log entries
reported newly built targets. This is not 1,694 recompilations. All nine copied
package revisions matched the destination lockfile and were checked again after
copying. These project preparations used approximately 8.8 GB before installing
additional toolchains. Remaining Mathlib environments are not silently
substituted or claimed prepared.

The three missing aarch64 Lean releases were subsequently installed in serial
inside `work/elan`, using the existing read-only Elan binary:

| Lean version | Compiler-reported commit |
| --- | --- |
| v4.25.0 | `cdd38ac5115bdeec5f609e9126cce00f51ae88b3` |
| v4.28.0 | `7e01a1bf5c70fc6167d49c345d3bf80596e9a79b` |
| v4.33.0-rc2 | `d8b18978322de05a8f3dba51ef03cf5461676c17` |

The installer completed successfully in 727.189 seconds. All three binaries
also returned their expected versions in an offline isolated command. Existing
required toolchains are linked, not copied or modified. Use the explicit
`--elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan`
with the exported `work/projects-prepared.json` manifest. At this checkpoint,
the volume used **17,277,227,008 bytes** (about 17.3 GB); the earlier capacity-test
image and bootstrap tools fit in the separate setup reservation. This is final
usage at the checkpoint, not a measured peak or an API-cost estimate.

`work/readiness-all-toolchains.json` inventories all 36 rows with no missing
toolchain gaps: 17 have prepared bindings and 19 still lack matching project or
dependency builds. **Readiness is not proof verification.** These installations
alone do not add verified rows or an Arena score. The new v4.25/v4.28/v4.33-rc2
toolchains have not yet been used to verify their corresponding corpus rows.

### Reproduced admission hazards fixed during provisioning

1. Strata's newer `module` prefix hid imported theorem bodies behind axiom-shaped
   exports. The old audit falsely rejected the unchanged v4.27 reference.
   `ArenaCheck.lean` now reads the same pinned imports' private data into a
   separate audit-only environment, checks exact declaration identities/types,
   and traverses the checked proof and its transitive dependencies. It does not
   expose private declarations during candidate elaboration or enlarge the axiom
   allowlist. Native tests cover legitimate exported proofs, private helper
   proofs containing a forbidden axiom, and private-name visibility on v4.27,
   v4.29.1 and v4.32. The existing non-module v4.26 path is retained.
2. fuse2fs reports whole-second ctime. A same-size edit within one second
   reproduced stale `Fingerprinter` stat reuse. `seals.py` now rehashes files
   with whole-second ctime, with a deterministic offline regression and a test
   run on the actual FUSE volume. This adds real hashing overhead; it does not
   claim atomic snapshots under concurrent mutation.

An early baseline also detected a concurrent edit to the existing `lean.py`
boundary and correctly returned `dependencies_changed_start_new_context`.
That observation was not admitted. Early failures remain in
`work/baseline-first.json`; intermediate runs were interrupted while fixing
the boundary. Neither their partial checks nor historical contexts are silently
counted as fresh evidence for the updated verifier.

### Regression commands actually run

```bash
python -m pytest -q --test-seal=off tests/test_arena.py tests/test_arena_lean.py tests/test_arena_prepare.py tests/test_arena_projects.py tests/test_arena_trial.py tests/test_arena_module_audit.py tests/test_router_tuning.py tests/test_proof_slicing.py tests/test_lean_refactor_corpus.py tests/test_kernel_boundary.py
# 266 passed, 45 skipped in 76.44s

python -m pytest -q --test-seal=off tests/test_seals.py
# 40 passed in 35.39s

TMPDIR=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp JEVOPS_ARENA_NATIVE_TESTS=1 python -m pytest -q --test-seal=off tests/test_arena_lean.py tests/test_arena_module_audit.py --tb=short
# 86 passed in 107.36s (45 native integration cases, 41 offline cases)
```

The full repository suite has not been rerun in this provisioning slice. These
tests include mock/offline checks as labeled; only explicit native integration
cases execute Lean. No score, newly optimized candidate, learned model result,
organizer submission, automatic promotion or continuous loop follows from
preparing an environment.

### Handoff checkpoint: corpus verification still running

The [provisioning evidence record](papers/completion/lean_refactor_arena/evidence/provisioning-2026-09-22.json)
records successful build/install commands, log hashes, resource usage, readiness
and the tests above. At that record's observation time, the following native
baseline was **still running**, with a 17-process budget. Its output is written
only after completion; no new corpus verification count or score is claimed at
this checkpoint. It is read-only against prepared inputs and has no build queue
or automatic optimization/promotion step. The provisioning containers have all
exited. Dependency fingerprinting on the coarse-timestamp FUSE volume is a
substantial remaining performance cost, not hidden as model or Lean latency.

```bash
TMPDIR=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp python -m jevops.arena_lean --baseline \
  --projects /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/projects-prepared.json \
  --max-processes 17 --timeout 180 \
  --output /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/baseline-prepared-audited.json
```

This in-flight run uses the original global toolchain home for its 17 already
prepared bindings; the separate readiness report uses the new isolated Elan
home and includes all downloaded versions. Do not interpret the older run's
initial toolchain inventory as a failure of the later successful installations.
Inspect its terminal receipts before counting additional verified rows. The
per-process timeout does not bound global fingerprinting time. There is no
automatic retry or crash-resume guarantee for the baseline runner.

## 16. Continuation: verified baseline and a further pinned Cslib environment

The in-flight baseline above has now completed. Its
[unaltered JSON report](papers/completion/lean_refactor_arena/evidence/native-baseline-prepared-2026-09-22.json)
contains **17 VERIFIED, 19 UNAVAILABLE**, with 17 native processes, no semantic
rejections and no runtime errors. This is five more verified version checks than
the original 12-check baseline: both additional Strata versions and three Cslib
v4.32 checks. All are unchanged reference proofs. No Arena score or optimization
gain follows. The report's SHA-256 is
`007c3f5b9ed8a5fbfd83215acda9f5a16a3ffdb6824ab8f57dbe68e166ce349b`.
Its 587,750 file reads and 1,532,854 stat-cache hits expose the substantial global
identity-checking work; these are not local neural inference costs.

Cslib v4.33.0-rc2 was prepared separately at
`3aa9d4416c185e0b9faeb72bbd65abe85b95dbcc`, using Mathlib
`51e6992efd06126df61a496bebf8f49482a4e129` and all eight other exact lockfile
dependencies. The original shared clones remain read-only. The serial runs were:

| Work | Network | Observed wall time |
| --- | --- | ---: |
| Independent local source clones, exact checkouts | Disabled | 36.446 s |
| Build pinned cache tool; fetch/extract 2,605 selected cached modules | Enabled | 665.030 s |
| Build dependencies of the three benchmark target modules | Disabled | 188.491 s |

The last command completed 1,697 Lake jobs, including cached work; only **28**
targets were newly built. At completion the capped volume used **20,749,053,952
bytes**. This is below the 50 GB decimal allowance, not a measured peak. No
toolchain substitution, shared mutable dependency links or paid inference was
used. `work/projects-prepared-20.json` retains all corpus bindings and adds this
prepared root. Its three target checks have **not** been counted as verified by
the 17-check baseline, which started before this environment existed.

One trial attempt failed before any native invocation because Git status on the
busy FUSE mount exceeded 10 seconds. A later readiness inventory similarly
reported one transient timeout (19 UNMEASURED, 17 UNAVAILABLE), rather than a
stable loss of a previously prepared project. Do not silently call that failed
inventory 20 ready checks. Further heavy checks should be serialized with
preparation using the existing lock, as documented in `ARENA_PREPARATION.md`.

The trial runner now preserves bounded preparation failures in incomplete
reports (`TIMEOUT`, `ERROR`, or `UNAVAILABLE`) with no fabricated receipt or
native invocation. Offline regressions cover binding and context failures and
reject a forged success in the preparation-error channel. Its optional
`proof_slice_unused_have` strategy selects single-line hypothesis cuts from the
existing bounded slicer, preserving the theorem envelope and case bodies.
Textual non-use is not semantic independence; contextual tactics can still need
the removed hypothesis. The unchanged `proof_slice` strategy is preserved.

After the native jobs became idle, a lock-held readiness recheck completed with
**20 UNMEASURED / 16 UNAVAILABLE** and no transient timeout, saved as
`work/readiness-prepared-20-idle.json`. Only 17 of those 20 prepared checks have
the baseline receipts above; the three v4.33-rc2 corpus proofs remain separate
work. The opt-in expanded native suite completed **124 passed, 16 skipped in
1007.81 seconds**. The skipped cases request the optional v4.34 toolchain, which
is absent from this isolated Elan home, not any of the three new corpus tags.
The final focused offline suite at this checkpoint completed **270 passed, 99
skipped in 36.85 seconds** (the skipped cases need explicit native opt-in).

The [complete Core cut trial](papers/completion/lean_refactor_arena/evidence/native-controlled-core-2026-09-22.json)
used 36 fresh native checks: 12 controls verified and both cuts were rejected
in all 24 candidate checks. A shorter unproved text is not a refactor gain.
Its diagnostics support a narrower next proposal: remove `Hlen2` together with
the corresponding induction-hypothesis argument and now-obsolete subgoal block.
That manual draft is recorded separately and submitted through the explicit
`--candidate` interface, not mislabeled as a historical successful seed or
trained policy output. It still requires the full controlled verification matrix.

### Completed repair experiment and current handoff

That matrix has now completed: **24/24 checks VERIFIED**, including twelve
unchanged controls and twelve repaired-candidate executions. The
[full repair report](papers/completion/lean_refactor_arena/evidence/native-controlled-core-repair-2026-09-22.json)
records **224 → 216 tokens (3.57% shorter)** and lower raw heartbeat counts in
every version/order stratum. Median reductions were approximately 37.89% on
v4.29.1, 41.32% on v4.27.0 and 42.40% on v4.26.0, in both orders. The runner
and native boundary source remained unchanged during this repaired run. This is
one new **manual, diagnostic-guided warm-up refactor**, not an automated/model
discovery, held-out generalization, elapsed-time speedup or official Arena score.
The original shared proof files and production memory were not changed.

The [continuation evidence record](papers/completion/lean_refactor_arena/evidence/provisioning-continuation-2026-09-22.json)
includes exact build commands and log hashes, artifact hashes, resource usage,
the two trial outcomes and test commands. Final focused tests in this slice:

```bash
python -m pytest -q --test-seal=off tests/test_arena.py tests/test_arena_prepare.py tests/test_arena_projects.py tests/test_arena_trial.py tests/test_arena_lean.py tests/test_arena_module_audit.py tests/test_seals.py
# 274 passed, 99 skipped in 36.58s

TMPDIR=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp ELAN_HOME=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan JEVOPS_ARENA_NATIVE_TESTS=1 python -m pytest -q --test-seal=off tests/test_arena_lean.py tests/test_arena_module_audit.py --tb=short
# 124 passed, 16 skipped in 1007.81s; 83 actually executed native cases
```

The full repository suite was not run. Saved-report tests reconstruct the
schedule and receipt/context identities; they are bookkeeping audits, not fresh
executions of those historical proofs. The volume used **20,749,795,328 bytes**
at the final observation, within the same 50 GB allowance.

A **finite three-process Cslib v4.33-rc2 baseline** was then started under the
existing single-build lock. At the evidence record's 23:08 UTC observation it
was still running (local PID 3892731), with output pending at
`work/baseline-cslib-rc2.json`. It uses `work/projects-cslib-rc2-only.json` and the
isolated Elan home, with `--max-processes 3 --timeout 180`. The output is written
only at completion; no additional Cslib verification is claimed yet. Other rows
will be unavailable in this deliberately restricted manifest, not a regression
of the full 20-binding readiness inventory. Do not start a concurrent build or
edit the native boundary while it runs. The process timeout does not cap global
fingerprinting time. This is not a continuous optimizer or an automatic retry
queue. Sixteen other version checks still need pinned environment preparation.
