# JevOps neurosymbolic cellular-automaton review

## Assessment

JevOps already contains most of the substrate for a neurosymbolic cellular
automaton, but the pieces are not yet one formal transition system.

| Layer | Existing implementation | Assessment |
| --- | --- | --- |
| Symbolic authority | `jevops.jev`, `jevops.oracle`, `jevops.lean`, closed tactic/fold transforms, `Lake`/consumer hooks | Strong: proposals are separated from proof/oracle admission. |
| Cell state | `jevops.nca`: canonical `ptr://` ids, grid, energy, wins/losses, journal, halt, fork/mutate | Strong substrate; cell fields are still ad-hoc dictionaries. |
| Neighborhood graph | board edges, JSON-LD, AST call graphs, plan/task DAG, graph message passing | Present, but `nca.neighborhood` currently makes skill cells broadly adjacent and several KG ids are not canonical cell ids. |
| Neural/statistical dynamics | scalar NCA tick, integer message passing, Bayes/Thompson/RF/MCMC/SVD, tape and autoencoder modules | Useful ranking and diffusion mechanisms; not yet a typed learned local update rule. |
| Action policy | `jevops.tactics.multi_armed_bandit`, `nca_bandit`, `port_bandit` | Now has explicit select → observe lifecycle and NCA/journal reflection. |
| Evolutionary outer loop | `jevops.harness` inner self-analysis, `jevops.outer` router, isolated candidate evaluator and exact-text patch gate | Safe and reproducible enough for bounded experiments; default evaluation is currently mostly binary pytest/compile success. |

## Current control flow

```text
inner AST/self-analysis
        ↓
NCA cells + graph/tape/plan state
        ↓
bandit selects a tactic/action arm
        ↓
Lake/tests/evaluator emit an explicit outcome
        ↓
NCA cell + posterior + journal update
        ↓
outer llm_router proposes one bounded JSON action
        ↓
isolated candidate evaluation → accept/reject exact source change
```

The new bandit tactic is intentionally not proof admission. A selected arm is
pending until the caller supplies a reward in `[0, 1]`; this avoids the old
delayed-bandit failure mode of inferring chronology from concatenated success
and failure lists.

## Prioritized work to become a real neurosymbolic CA

1. **Unify transition evidence.** Add one versioned event shape containing
   `tick`, `cell`, `neighbors`, `action`, `proposal_id`, `oracle`, `reward`,
   and `accepted`. Feed lake/test results, bandit observations, and outer code
   evaluations through it. Do not reconstruct time from separate aggregate
   lists.

2. **Make locality explicit.** Use board edges, call-graph edges, plan edges,
   and typed residual links as the neighborhood. Remove the complete
   skill-to-skill fallback or cap it to a deterministic local window. Canonicalize
   every edge before a tick so symbolic and neural layers address the same cell.

3. **Define a typed cell schema.** Replace unconstrained dictionaries at the
   transition boundary with a versioned shape: identity/kind, bounded feature
   vector, energy, posterior, safety flags, pending actions, age, and receipt
   references. Keep JSON compatibility at the persistence boundary.

4. **Implement a synchronous local rule.** Each tick should read an immutable
   snapshot, compute bounded relation-specific neighbor messages, apply a
   deterministic rule or seeded policy, and commit a validated delta. The
   existing `nca.tick` already uses a next-grid for scalar energy, which is a
   good starting point; it needs typed messages and explicit conflict handling.

5. **Use a multi-objective evaluator.** A feature can be valid even when it
   does not change the test count. The harness currently accepts a code change
   only when its scalar evaluator improves (unless `accept_equal` is enabled),
   so a feature with unchanged tests is rejected by design. Add metrics for
   invariant coverage, regression status, latency, memory growth, replay
   determinism, and code complexity; require non-regression on tests while
   allowing a declared secondary metric to improve.

6. **Bound and replay state.** Cap grid/edge/observation stores, persist a
   schema version and random seed, and make journal replay produce the same
   state hash. Continuous operation should compact old receipts instead of
   allowing `nca` memory to grow without a policy.

7. **Keep proposal and commit planes separate.** The inner CA may rank and
   select actions; the outer router may propose source changes; only the
   isolated evaluator and exact-text gate may commit them. This preserves the
   current safety boundary while allowing richer learning.

## Recommended next implementation slice

The highest-value next slice is a `TransitionEvent`/`CellDelta` schema in
`jevops.nca`, followed by canonical local neighborhoods and a vector-valued
double-buffer tick. Then connect `JevOpsHarness` evaluation receipts to the
 bandit observer as a named reward source. That makes the inner loop learn which
 closed tactics improve the harness while the outer `llm_router` remains the
 bounded code-proposal mechanism.
