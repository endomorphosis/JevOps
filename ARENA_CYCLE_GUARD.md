# Conservative branch-cycle guard

This note documents `cycle_key="raw-v1"`. The separately opt-in
[assigned-value extension](ARENA_ASSIGNED_CYCLE_GUARD.md) follows existing
assignments without solving unresolved constraints; raw-mode behavior remains
unchanged.

The proposition-discharge trial repeatedly applied the same lemmas without a
complete proof. Repeated names or raw goal heads do **not** show that those
states are equivalent. This opt-in extension tests exact repeats inside the
existing native AND/OR search; it does not add another prover or admission path.

```python
batch = runtime.discover_batch(
    pin, capture, index, scope,
    search="subgoal-v1", retrieval="typed-head-v1", span_order="matching-head-v1",
    max_steps=96, max_depth=8, max_applications=4, cap=1,
    cycle_guard="prune-v1", max_cycle_checks=256,
)
```

The guard also works with fixed-pool `backward-v1`, and independently of sibling
discharge. The default `cycle_guard="none"` preserves V1–V4 reports and existing
request options. `observe-v1` inspects repeats without pruning; `prune-v1` stops
only the repeated branch. Both opt-in modes produce V5 receipts. No live model,
API, project build or download is enabled by these options.

## Eligibility and exact identity

`inspectCycleGoal` reads the current goal's actual local context. It refuses
contexts with over 64 declaration slots (including tombstones) or 64 local
instances, and stops traversing after 2,048 expression nodes. Overflow abstains
from comparison; it never compares a truncated key. Persistent-array size is
checked before traversing declarations, avoiding an unbounded `LocalContext.size`
scan. The bounds are fixed by this version of the implementation.

Eligible keys contain:

- The exact goal type, checked to inhabit `Prop`.
- All local declarations in order: identities, indices, names, types, binder
  information, declaration kinds, and let values/nondependency flags.
- Local instance expressions and class names, auxiliary declaration names,
  and the declaration-slot count.

All these expressions must be free of raw expression and universe metavariables.
Even an already assigned but syntactically present metavariable causes abstention.
Rigid free variables and universe parameters are allowed; their identities are
not renamed. The guard does **not** normalize, instantiate assignments, compare
pretty strings, or infer equality from a hash. It uses Lean's structural
`Expr.equal`, not the weaker default alpha-equivalence comparison. The native
environment/options stay fixed within a search invocation; keys are never
shared between invocations, pins, sources or captures.

Only propositions are eligible: repeatedly constructing a data goal such as
`Nat` under `Nat.succ` can produce a useful different witness. Such repetition
must not be pruned. Prop checking may perform elaborator work, but the entire
saved state (including metavariables, diagnostics and information state) is
restored after inspection, also on exceptions.

## Branch locality, accounting and trust boundary

Each pending goal has its own immutable ancestor list. Only newly generated
children inherit the expanded goal's ancestors. Siblings retain their own
histories, including when discharge rotates the frontier. Backtracking discards
the speculative history with the branch. An ineligible inspection breaks the
ancestor chain conservatively. No global visited or negative-result cache is
introduced. Identical independent sibling obligations are still proved twice.

Checks occur before generative expansion, after optional sibling discharge and
the depth cutoff. Discharge may therefore already close a repeated proposition.
Every inspection reserves a separate unit **before** inspecting state, with a
maximum of 256 per process. Reaching that ceiling stops search explicitly; zero
prevents process launch. Counts survive backtracking. Primitive attempts,
retrievals, discharge checks and cycle checks remain separate nonrefundable
budgets. Timeouts retain reservations and report unknown internal work.

Each V5 check records `id`, `at_step`, `depth`, `kind`, `nodes`, `declarations`,
`repeat_of`, and `decision`. Outcomes distinguish eligible keys, metavariables,
non-propositions, context/node limits and errors. The ancestor reference points
to an earlier eligible native observation; it is not a proof certificate.
The Python boundary rejects invalid chronology, bounds, modes, counter totals,
ancestor references and decisions. It cannot reconstruct structural equality
from this diagnostic summary. Fixtures remain labelled fixtures.

Neither a match nor a prune establishes truth or falsity. Every successful path
still needs independent script replay, kernel/type/axiom checking, bounded term
materialization and independent term replay. Only strictly shorter source drafts
leave discovery; whole-source all-pin checking and measured-cost admission remain
separate. Failed search and pruned branches are not counterexamples.

The node counter measures the explicit expression traversal, not every operation
inside Lean. Name/level comparisons, structural comparisons and Prop inference
also cost work; process deadlines and native heartbeats remain in force. Error
observations do not establish complete internal-work counts. Inspection overhead
must not be hidden by reporting only fewer primitive attempts.

## Limits and evaluation protocol

This is deliberately incomplete repeat detection. Definitional equality,
alpha-renaming, changed local contexts, assigned raw metavariables and different
constraints can prevent a match. We make no completeness guarantee for Lean
search, particularly under finite budgets or the existing proposition-only
discharge policy. Soundness of emitted proofs still comes from replay, not an
assumed completeness theorem about pruning.

`run_local_premise_pilot.py --comparison cycle-guard` declares three fixed arms:
the preceding proposition-only search, observation-only cycle checks, and active
pruning. It keeps the same nominees, source events, discharge mode, depth eight,
96 primitive attempts, 32 retrievals, 256 discharge checks and four discovery
invocations per arm. Observed arms each allow 256 cycle checks per invocation.
Their only difference is whether an eligible repeat prunes. Original controls,
inventory, fresh capture, all-pin screening and potential balanced measurements
use the existing capped-volume, exclusive-run and read-only snapshot boundaries.
With three pins and one draft slot, the maximum process allowance is 76.

The task is exploratory public warmup, not held-out evaluation. Single serial
wall times cannot demonstrate speedup; synthetic controls cannot establish an
Arena win. No strategy is promoted automatically.

## Validation commands

From the repository root, offline regression selection (not the entire repo):

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_cycle_guard.py tests/test_proposition_discharge.py \
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

Native controls, separately for each installed toolchain (no downloads/models):

```bash
env JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_SEARCH_LEAN_TAG=v4.26.0 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_cycle_guard.py -k native

env JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_SEARCH_LEAN_TAG=v4.29.1 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_cycle_guard.py -k native
```

Offline controls validate malformed receipts, zero/exact limits, timeout
accounting, request identity, legacy defaults, batch propagation and pilot
orchestration. Native controls exercise direct/mutual cycles, alternative valid
proofs, independent duplicate siblings, new local contexts, failed-branch
rollback, axiom rejection, raw assigned/unassigned term and universe metas,
data goals, changed let values/instances/auxiliary names, context/node overflow,
exact/one-below check budgets, and composition with proposition-only discharge.
Observation-only mode must reproduce the disabled guard's primitive trace and
proof path in the native chain control. Tests do not establish Lean-search
completeness or a cross-process concurrency guarantee.

Observed on 2026-09-24 with the final runtime implementation:

| Command | Result |
| --- | --- |
| Offline regression selection above | 817 passed, 69 skipped, 9 deselected; 11.63 s |
| Native controls, Lean 4.26.0 | 12 passed, 31 deselected; 130.73 s |
| Native controls, Lean 4.29.1 | 12 passed, 31 deselected; 130.01 s |

Earlier development runs exposed an older Lean map-lookup API mismatch and
overstrong test expectations for a generic lemma whose raw goals retained
metavariables. Those were corrected before the final runs: monomorphic
exact-cycle controls test pruning, while separate raw-meta controls explicitly
require abstention. A context-growth control uses a bounded depth-four protocol;
it does not assume that finite search will solve every valid proof.

Changed implementation files are `jevops/lean/ArenaLocal.lean` (keys, inspection,
branch histories, guard and native accounting), `jevops/arena_local.py` (V5
validation, bound requests and accounting), `jevops/arena_providers.py` (opt-in
plans), and the existing `run_local_premise_pilot.py` (fixed three-arm protocol).
`tests/test_cycle_guard.py` supplies the new controls; the sibling-order helper
and pilot orchestration tests were extended without changing their defaults.
This note and README describe the interface and its limits. No dependency was
added and no legacy search policy was enabled by default.

## Frozen Core result

The [three-arm native trial](papers/completion/lean_refactor_arena/evidence/cycle-guard-pilot-2026-09-24/README.md)
finished with **zero shorter drafts and zero pruned cycles**. All arms used 349
primitive attempts, 47 retrievals and 310 discharge inspections, with identical
primitive/retrieval/discharge traces. Cycle-aware arms each added 51 inspections
and 5,090 explicit expression-node visits. Forty-eight keys contained raw
metavariables; the three eligible keys were not repeats. The compact log does
not distinguish assigned from unresolved metavariables or locate them within
the context. There is no measured Arena win or demonstrated efficiency gain.

Original controls verified on all three pins. Total: 19 native processes,
499.2063 seconds, no API/model/build/download, no candidate screening or
measurement, no promotion. The snapshot remained unchanged. The guard stays
opt-in; the subsequently implemented assignment-aware mode is documented in
[its separate guide](ARENA_ASSIGNED_CYCLE_GUARD.md).
