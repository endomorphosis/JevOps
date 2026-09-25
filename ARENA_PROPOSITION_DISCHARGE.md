# Proposition-only sibling discharge

The [previous Core ordering trial](papers/completion/lean_refactor_arena/evidence/subgoal-ordering-pilot-2026-09-24/README.md)
produced no shorter drafts and increased primitive work from 304 to 374. Its
trace included data-valued goals as well as proof obligations. This extension
tests that diagnosis without treating a successful hypothesis match as a
verified refactor, or assuming every pending goal is a proposition.

## Use and compatibility

```python
batch = runtime.discover_batch(
    pin, capture, index, scope,
    retrieval="typed-head-v1", span_order="matching-head-v1",
    search="subgoal-v1", max_pool=64, max_retrievals=32, retrieval_top_k=4,
    discharge_window=8, discharge_filter="propositions-v1",
    max_discharge_checks=256, max_steps=96, max_depth=8,
    max_events=64, max_applications=4, cap=1,
)
```

The default filter is `none`: V1/V2/V3 behavior, schemas and default plan
identities remain supported. Non-`none` filters require the existing positive
discharge window and scoped subgoal pool. The low-level `discover_search` API
accepts the same options, but still relies on its caller to provide a trusted
scope. The batch planner enforces existing inventory/dependency/split exclusions.

Two V4 modes use the **same** inspection procedure and bounds:

- `observe-all-v1`: record goal kinds, then attempt every previously eligible
  discharge, including data and unknown sorts. This is the observational
  control for the old ordering algorithm, not the preferred policy.
- `propositions-v1`: only attempt discharge of goals classified `prop`. Record
  skips of data, unknown sorts and classification errors separately.

Skipping a data goal does not accept it or remove it from the logical frontier.
It may subsequently be solved by an explicit rule/constructor or by assignments
induced while proving another premise. In particular, proposition-only discharge
**does not prevent all witness assignments**: a proposition such as `P ?x` can
still constrain `?x`. Alternative matching hypotheses are not enumerated.

## Read-only sort classification and accounting

Inside the goal's actual Lean context, `inspectDischargeGoal` obtains its type,
infers and weak-head reduces that type's type, and inspects the universe of the
resulting `Sort`. It uses Lean's `Level.isAlwaysZero` / `isNeverZero` after
instantiating existing universe assignments:

| Kind | Meaning |
| --- | --- |
| `prop` | Inferred sort is always `Sort 0` (`Prop`). |
| `data` | Inferred sort's level is definitely nonzero. |
| `unknown` | Universe parameters/metavariables or another unresolved form prevent either conclusion. |
| `error` | Classification raised an exception; no kind was established. |

An unknown universe is not silently classified as data or Prop. Aliases are
handled by type inference, not declaration spelling. A goal whose *type is*
`Prop` asks for a proposition as a value; that is different from proving a goal
whose type itself inhabits `Prop`.

The whole elaborator state is saved and restored around inspection, including
metavariable/universe assignments, messages and information state. Even successful
inspection is observational. Normal proof search retains its separate full-state
rollback when a later sibling fails.

Each inspection is reserved **before** reading Lean state, against an independent
integer allowance of at most 256 per process. Zero prevents launching the mode.
Reservations and observed checks survive search rollback. Reaching the check
limit explicitly exhausts that search; it does not silently resume unfiltered.
Primitive and retrieval budgets remain independent. A skipped goal consumes an
inspection unit, **not** an attempted `assumption` unit. A timeout retains full
reservations and reports unknown internal work instead of fabricating zero.

This is not constant-time metadata: inference/reduction, local-context search,
and frontier pruning have variable costs. Existing native heartbeat settings,
process deadlines and output caps still apply. The bounded raw head (at most
256 spine visits and 1,024 bytes) is recorded only for diagnosis, not classification
or proof authority. No full local proof values or whole-runtime objects are exposed.

## V4 trace and unchanged proof boundary

V4 receipts bind the filter and inspection ceiling in addition to all existing
source/capture/pin/context, pool, depth and primitive limits. Each check records:

```text
id, at_step, depth, goal_index, head, kind, decision
```

`at_step` is the number of charged primitive attempts before inspection. Multiple
skips can share that offset. Every attempted discharge links its unique `check_id`
to the exact charged primitive row; expansion rows must have a null check ID.
The Python boundary checks bounds, chronology, unique linking, goal/depth/step
agreement and the policy decision implied by the kind. Unsupported fields,
counter mismatches, skipped-but-executed checks, uncharged attempts and forged
replay receipts are rejected.

The kind is a trusted-native search observation, **not independently reconstructed
evidence of truth at the Python boundary**. It cannot admit a fact or a refactor.
Every successful path must still replay from the original before-context,
pass kernel/type/axiom checks, materialize to a bounded explicit term and replay
that term independently. Whole-source all-pin screening and measured cost gates
remain separate. Fixtures are explicitly fixtures, never native verification.

## Controls and frozen comparison

`tests/test_proposition_discharge.py` covers malformed evidence, zero/exact
budgets, timeout accounting and plan identity offline. Native controls cover
propositional sibling constraints, rollback after a wrong successful match,
conjunction, list/function data goals, aliases, unresolved universe sorts,
axiom rejection and exact/one-below inspection budgets. The observation-only
control must reproduce legacy primitive actions, queries and proof paths; its
extra metadata is removed only for that comparison, not from the evidence log.

`--comparison proposition-discharge` adds three fixed arms to the existing pilot:

1. Baseline dynamic retrieval without sibling discharge.
2. Sibling discharge with `observe-all-v1`.
3. Sibling discharge with `propositions-v1`.

All use the same task, nominees, fresh capture, depth eight, top-k four, 96-step
and 32-query ceilings per invocation, four search processes and one draft slot.
The observed arms each have 256 inspections per process; the baseline has no
inspection overhead. Arms two and three differ only by the filter. Actual work
is not matched or hidden. The three-pin Core protocol reserves at most **76**
processes: 19 controls/discovery, nine possible screens, 48 possible measurements.
It uses the existing exclusive build lock, 50-GB capped volume and immutable
snapshot. No model, API, downloads or project builds are required here.

This is public-warmup, reference-informed exploration, not held-out evaluation.
There is no automatic promotion or official Arena score. Finite-budget search
can still miss valid proofs, including proofs needing a data-valued hypothesis.
No completeness or general performance improvement is claimed.

## Real-corpus result

The [frozen Core trial and complete traces](papers/completion/lean_refactor_arena/evidence/proposition-discharge-pilot-2026-09-24/README.md)
completed in 518.3151 seconds using 19 native processes. All three original
controls verified, but **no arm produced a shorter draft**. Baseline used 304
primitives; observe-all used 374 plus 156 inspections; proposition-only used
349 plus 310 inspections and skipped 135 data attempts. This is not an
established efficiency or Arena-score improvement. The option stays disabled.

The new observations confirm that 16 of the 17 prior successful later-goal
discharges were data-valued, not propositions. Observe-all reproduced the
prior run's complete primitive and retrieval traces for all four events.
The filtered mode fixes that specific behavior, but repeated rule expansion
still exhausts the search before all siblings close. Guarded cycle detection,
alternative expansion scheduling, and a late data-hypothesis fallback remain
separate, unevaluated work. See the report for per-event regressions and bounds.

## Files

- `jevops/lean/ArenaLocal.lean`: restorative sort inspection, explicit skips,
  non-refundable observation budget and V4 receipts within the existing search.
- `jevops/arena_local.py`: validates the new protocol and aggregates real counts.
- `jevops/arena_providers.py`: opt-in settings and bounded planning.
- `tools/run_local_premise_pilot.py`: matched filter/observation protocol.
- `tests/test_proposition_discharge.py`, `tests/test_subgoal_ordering.py`, and
  `tests/test_local_premise_pilot.py`: controls and legacy regression coverage.
- This note, README and the experiment evidence: use, limits and actual results.

## Observed test commands (2026-09-24)

Tests below actually ran with test-seal reuse disabled. They are selected
regressions, not the complete repository suite. Fixtures do not invoke Lean.

Focused offline: **86 passed, 14 skipped**, 1.77 seconds:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_proposition_discharge.py tests/test_subgoal_ordering.py tests/test_local_premise_pilot.py
```

Expanded offline: **784 passed, 57 skipped, 9 deselected**, 11.97 seconds:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_proposition_discharge.py tests/test_subgoal_ordering.py \
  tests/test_subgoal_retrieval.py tests/test_local_backward_search.py \
  tests/test_typed_premises.py tests/test_local_application.py tests/test_arena_local.py \
  tests/test_local_premise_pilot.py tests/test_local_premise_replay.py \
  tests/test_local_tactic_portfolio.py tests/test_arena_premises.py tests/test_arena_providers.py \
  tests/test_premise_search.py tests/test_arena.py tests/test_arena_trial.py tests/test_arena_pareto.py \
  tests/test_refactor_prompts.py tests/test_refactor_prompt_archives.py tests/test_scoped_proposals.py \
  -k 'not native_generated and not before_context_never_copies and not stale_capture_abstains and not native_admission'
```

Lean 4.26 new native controls: **8 passed, 36 deselected**, 112.04 seconds:

```bash
env JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_SEARCH_LEAN_TAG=v4.26.0 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_proposition_discharge.py -k native
```

The old sibling-ordering `constraining` native control also passed on 4.26
(one passed, 26 deselected, 15.04 seconds) immediately after the native extension.

Lean 4.29 new and selected legacy native checks: **17 passed, 140 deselected**,
225.79 seconds:

```bash
env JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_SEARCH_LEAN_TAG=v4.29.1 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_proposition_discharge.py tests/test_subgoal_ordering.py \
  tests/test_subgoal_retrieval.py tests/test_local_backward_search.py \
  -k 'native and (proposition or goal_classification or constraining or rollback or conjunction or chain)'
```
