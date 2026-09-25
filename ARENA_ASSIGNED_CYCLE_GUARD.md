# Bounded assignment-aware cycle keys

The [raw-key trial](papers/completion/lean_refactor_arena/evidence/cycle-guard-pilot-2026-09-24/README.md)
found no repeats: 48/51 inspections encountered raw metavariables. It could not
tell whether those placeholders were already assigned. This extension follows
existing assignments before comparing a goal with its own ancestors. It is
separate from constraint solving, normalization, proof admission and training.

```python
batch = runtime.discover_batch(
    pin, capture, index, scope,
    search="subgoal-v1", retrieval="typed-head-v1", span_order="matching-head-v1",
    max_steps=96, max_depth=8, max_applications=4, cap=1,
    cycle_guard="prune-v1", cycle_key="assigned-v1", max_cycle_checks=256,
)
```

Defaults remain `cycle_guard="none"`, `cycle_key="raw-v1"`. Explicit `raw-v1`
does not change previous request options/identities. The assigned key requires
an enabled guard and is supported with both fixed-pool and dynamic backward
search. `observe-v1` computes the same keys without pruning. New keys use V6
receipts; V1–V5 remain supported. Old native captures still require their original
implementation identity and cannot be reused after changing driver code.

## Exact operation and resource bounds

`resolveCycleExpr` and `resolveCycleLevel` read Lean's existing term and universe
assignment tables. They follow transitive assignments and rebuild expressions
structurally, preserving binder names/information, let flags, metadata,
projections, constants and universe structure. They never call `isDefEq`, create
fresh metavariables, solve constraints, synthesize delayed assignments, or
perform beta/delta reduction or universe simplification. This is deliberately
weaker than general Lean normalization.

Every expression or universe node visit is charged **before** inspecting it.
Each key has a combined 2,048-visit cap and recursion depth below 128. Following
an assignment consumes a visit for the metavariable and separately visits its
value. Repeated references are charged again, without a global cache or refunds.
Large shared expansions and even malformed cyclic assignments terminate at the
caps. Limits reject the whole key; no truncated key is compared.

The existing 64-declaration-slot and 64-local-instance bounds apply before any
context traversal. After substituting the goal type, all local types, all let
values (including nondependent lets), and local-instance expressions, a second
check requires every expression to be metavariable-free. All declaration
identities, order, names, flags, auxiliary names and instance class names remain
part of the key. The resulting goal must be a proposition. Data/witness goals
are never cycle-pruned.

The entire tactic/elaborator state is saved and restored around inspection,
including diagnostics, information state and any incidental work by Prop
classification. Assignment chains are not compressed into the live context.
Keys are immutable snapshots of their resolved expressions. Changed assignments
after rollback produce different keys; unresolved and delayed assignments abstain.
The environment/options remain fixed per invocation, and histories remain
branch-local, not a global failed-goal cache. Independent siblings do not inherit
each other's history.

The separate integer inspection allowance is reserved before native work.
Zero prevents launch; exhaustion stops further search through the existing
guard budget. Timeouts retain reservations and expose unknown internal work.
Expression/universe visits do not measure every operation: structural comparisons,
names/metadata and Prop inference have additional costs. Existing heartbeats,
output limits and process deadlines remain in force.

## V6 observations and proof boundary

Each cycle check retains V5 identity, chronology, decision and ancestor fields,
and adds:

```text
expr_nodes, level_nodes, term_dereferences, level_dereferences, blocked_in
```

`nodes = expr_nodes + level_nodes` in this mode. Raw V5 `nodes` counts expression
visits only, so the two totals are not interchangeable cost units. Batch reports
expose the four new counters separately. Counts survive failed branches.

New abstention kinds distinguish `unresolved_term`, `unresolved_level`,
`delayed_assignment` and `depth_limit`, alongside context/node limits and errors.
`blocked_in` identifies the **first** blocked region: goal, local type, local
value or instance. Successful keys, non-propositions and context-limit outcomes
have no blocked region; errors may identify Prop classification. It is not an
inventory of all constraints or all assignments. No local proof text is exposed.

The Python boundary checks the mode/source binding, schemas, chronology,
ancestor references, node sums, dereference bounds and kind/location consistency.
It does not reconstruct state equality from these summaries. Fixtures remain
fixtures; hashes establish content identity, not truth. Errors and abstentions
are not counterexamples, cache hits, wins, or independently verified facts.

Every successful search still independently replays its script, checks the
proof's type/axioms, materializes a bounded explicit term and replays that term.
Only strictly shorter drafts proceed to separate whole-source all-pin checks
and measured-cost admission. Key matching or successful partial applications
cannot bypass this boundary. No general completeness claim is made for Lean
search or for finite-budget pruning.

## Frozen comparison protocol

The existing pilot now accepts `--comparison assigned-cycle`. Its three arms
are raw-key pruning, assigned-key observation only, and assigned-key pruning.
The last two differ only in the pruning decision; comparing raw with assigned
pruning isolates the key representation. The scoped nominees, event selection,
proposition-only discharge, depth, primitive/retrieval/discharge/check ceilings
and replay gates stay fixed. No late data fallback or larger search budget is
mixed into this experiment.

Four native discovery invocations and one shorter-draft slot per arm; depth
eight, 96 primitives, 32 retrievals, window eight, 256 discharge inspections
and 256 cycle inspections per invocation. With three pins, the maximum native
process allowance is 76, including possible screening and balanced measurements.
Actual key work is not matched. The task is exploratory public warmup, not a
held-out evaluation. Single-run serial timings cannot establish a speedup.

## Tests and changed files

`tests/test_assigned_cycle.py` checks V6 rejection, counters, zero/timeouts,
legacy identities and the fixed protocol offline. Native tests cover transitive
term/universe assignments, raw-mode compatibility, unchanged assignment tables,
unresolved goal/local-type/local-value constraints, delayed assignments, changed
assignments after rollback, data exclusion, recursion/node bounds, generic
identity-rule cycles, independent siblings, axiom rejection, exact check budgets,
and composition with the existing sibling-discharge rollback controls.

Implementation extends `jevops/lean/ArenaLocal.lean`, `jevops/arena_local.py`,
`jevops/arena_providers.py` and the existing `run_local_premise_pilot.py`.
The cycle/sibling test helpers and pilot orchestration fixtures were extended;
their previous defaults are unchanged. No dependency, external endpoint or
parallel agent framework was added. Native tests use installed toolchains only.

Focused offline command:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_assigned_cycle.py tests/test_cycle_guard.py tests/test_local_premise_pilot.py
```

Native commands, run serially:

```bash
env JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_SEARCH_LEAN_TAG=v4.26.0 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_assigned_cycle.py -k native -x

env JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_SEARCH_LEAN_TAG=v4.29.1 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_assigned_cycle.py tests/test_cycle_guard.py -k native -x
```

Expanded offline regression command (a selected suite, not the entire repository):

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_assigned_cycle.py tests/test_cycle_guard.py tests/test_proposition_discharge.py \
  tests/test_subgoal_ordering.py tests/test_subgoal_retrieval.py \
  tests/test_local_backward_search.py tests/test_typed_premises.py \
  tests/test_local_application.py tests/test_arena_local.py \
  tests/test_local_premise_pilot.py tests/test_local_premise_replay.py \
  tests/test_local_tactic_portfolio.py tests/test_arena_premises.py \
  tests/test_arena_providers.py tests/test_premise_search.py \
  tests/test_arena.py tests/test_arena_trial.py tests/test_arena_pareto.py \
  tests/test_refactor_prompts.py tests/test_refactor_prompt_archives.py \
  tests/test_scoped_proposals.py \
  -k 'not native_generated and not before_context_never_copies and not stale_capture_abstains and not native_admission'
```

Observed validation on 2026-09-24:

| Run | Result |
| --- | --- |
| Focused offline | 88 passed, 21 skipped; 1.76 s |
| Expanded offline selection | 843 passed, 78 skipped, 9 deselected; 12.44 s |
| New native controls, Lean 4.26.0 | 9 passed, 24 deselected; 111.35 s |
| New and legacy native controls, Lean 4.29.1 | 21 passed, 55 deselected; 249.75 s |

The strengthened shared-expansion and context-overflow assertions in
`test_native_assignment_boundaries` were subsequently rerun on each toolchain:
one passed, 32 deselected in 2.20 s (4.26.0) and 2.10 s (4.29.1). Those commands
are the native commands above with only `tests/test_assigned_cycle.py` and
`-k boundaries`. These are repeat executions, not additional distinct Arena wins.

The generic identity-rule control now prunes repeated, fully instantiated
propositions and closes its alternative proof with fewer primitive attempts
than observation-only search. Both script/term replay and a separate whole-source
check must succeed. Observation-only search reproduces the disabled guard's
primitive trace and path in that control. This synthetic result does not predict
an Arena score or prove completeness of pruning.

## Real Core comparison

The [frozen three-arm pilot](papers/completion/lean_refactor_arena/evidence/assigned-cycle-pilot-2026-09-24/README.md)
finished in 513.9291 seconds with 19 native processes. Original controls verified
on all three pins. Each arm produced **zero shorter drafts**, with identical
349-primitive, 47-retrieval and 310-discharge-inspection traces. No candidate
reached source screening or measurement; there is no new Arena score.

Assigned-key inspections followed 277 existing term assignments per arm and
increased eligible keys from 3/51 to 17/51, but none was an exact ancestor
repeat. The remaining 34 inspections first encountered an unresolved term in
the goal. Each assigned arm visited 6,371 expression and 491 universe nodes;
the raw arm visited 5,090 expression nodes. This is more inspection work without
an observed search benefit, not a speedup. All caps stayed fixed and no timeout,
key overflow or inspection error occurred. The option remains disabled by
default. A separately controlled late data-discharge experiment is a possible
next step, not a result implemented here.
