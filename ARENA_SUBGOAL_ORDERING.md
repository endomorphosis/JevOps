# Budgeted, reversible sibling discharge

The [subgoal retrieval trial](papers/completion/lean_refactor_arena/evidence/subgoal-retrieval-pilot-2026-09-24/README.md)
found intermediate lemmas but still produced no shorter drafts. Its trace
suggested that the first, generative premise could instantiate an intermediate
store before a later `UpdateState`/`UpdateStates` premise constrained that store.
This is a search diagnosis, not a claim that ordering alone solves the task.

## Opt-in implementation

The existing native AND/OR search now accepts `discharge_window=8`:

```python
batch = runtime.discover_batch(
    pin, capture, index, scope,
    retrieval="typed-head-v1", span_order="matching-head-v1",
    search="subgoal-v1", max_pool=64, max_retrievals=32, retrieval_top_k=4,
    discharge_window=8, max_depth=8, max_steps=96,
    max_events=64, max_applications=4, cap=1,
)
```

Zero is the default **disabled ordering option**, not a resource allowance.
Values 1–16 enable the mode; 1 tests only the first live goal. Zero primitive,
depth or retrieval allowance still prevents launching native search. Nonzero
ordering requires an explicit scoped subgoal pool. Existing V1/V2 reports,
requests and defaults remain supported.

At each search node the new mode:

1. Removes assigned goals from the frontier and tries Lean `assumption` on the
   first at most `discharge_window` live goals, in order. Every try consumes one
   of the **same** primitive operation units, whether it fails or succeeds.
2. If a hypothesis closes a goal, searches the remaining, rotated frontier with
   those metavariable assignments. If any downstream work fails, restores the
   complete saved elaborator state (including information state) and tries the
   next alternative. A successful unification is not an irreversible commitment.
3. If the bounded discharge alternatives fail, returns to expansion of the
   first goal using the existing scoped applications, intro and constructor.
   It does not retry that node's already-tested first-goal assumption. A raw-head
   query is needed for expansion, not for a direct local-hypothesis check.

Counters live outside the restored state: rollback never refunds attempts or
queries. Depth limits apply to discharge as well as expansion. The window only
bounds the number of hypothesis-discharge attempts per node, **not** the number
of local declarations Lean's `assumption` inspects internally. Frontier pruning
visits the pending goal list. Lean's own heartbeat limit, process deadline and
output cap still bound this work; an operation unit is not a constant-time unit.
No model, learned weights, external prover or new library dependency is used.

## Evidence and replay

The `jevops-local-search/v3` receipt binds the window as well as all previous
source, capture, environment, pin, pool and resource settings. Each primitive
has a phase (`discharge` or `expand`), a zero-based live-goal index, depth,
applied flag and retrieval reference. Only `assumption` can target a nonzero
index. Its null query reference means a local hypothesis check; expansion still
requires the root shortlist or a recorded subgoal query.

Successful paths contain `{action, goal_index}` records. Python checks their
bounded indices and allowed actions, and requires the path to be a chronological
subsequence of successful, charged trace operations. It constructs the exact
script expected from the native report. For a later goal the script includes:

```lean
(all_goals skip); (rotate_left 1); (focus (assumption))
```

Pruning before rotation is necessary: a previous tactic can assign a sibling
metavariable while leaving it in Lean's raw goal list. These administrative
commands do not add proof inference; their real execution cost is included in
native wall time. An index is not a proof or a stable cross-context identifier.

The complete script is then freshly replayed from the original before-context,
kernel/type/axiom checked, materialized to a bounded explicit term and
independently replayed again. Only a shorter source replacement becomes a draft.
All-pin whole-source screening and matched measurement remain separate gates.
Neither successful speculative discharge nor successful search is a promotion.

## Controls and comparison

`tests/test_subgoal_ordering.py` contains labelled offline receipt/forgery/budget
controls and explicitly opt-in installed-Lean tests. Native controls cover
shared metavariables, a useful later sibling, restoration after a **successful
but ultimately wrong** sibling discharge, conjunction, missing premises,
window-one limitations and exact/one-below primitive budgets. The examples use
ordinary definitions, not extra axioms or mock proof verification.

Run offline controls without API/model access:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --test-seal=off -p no:cacheprovider \
  tests/test_subgoal_ordering.py tests/test_subgoal_retrieval.py \
  tests/test_local_premise_pilot.py tests/test_local_backward_search.py
```

Native tests require explicit `JEVOPS_ARENA_NATIVE_TESTS=1` and an already
installed `JEVOPS_SEARCH_LEAN_TAG` (tested results are recorded below, not implied
by this command). They do not download toolchains or contact a model.

The frozen pilot adds `--comparison subgoal-ordering`. Its baseline and discharge
arms differ **only** by the latter's window of eight. Both use depth eight,
96 primitive attempts, 32 subgoal queries, top-k four and four span invocations.
They share a fresh all-pin inventory and original capture, with cap one draft
per arm. With the three-pin Core task, the full reservation ceiling is 57:
15 control/discovery + 6 screening + 36 possible measurement processes.
Actual work can differ. Discovery order is fixed baseline then discharge;
single-run wall times are not speedup evidence. No confirmation or promotion
is automatic. Execution still requires the reviewed readonly source snapshot,
exclusive build lock and existing capped volume.

## Limitations

`assumption` chooses one matching local declaration deterministically. This
search does not enumerate every matching hypothesis. Within finite limits the
new ordering can help, be neutral, or consume budget needed by another branch.
There is no completeness or universal speedup claim. The bounded window can
miss a useful distant sibling. Normalization/rewrite search, model-guided policy
training, live-model comparisons, held-out evaluation and broad corpus trials
remain separate work. This slice does not change any axiom or admission policy.

## Real-corpus result and changed files

The [frozen two-arm Core pilot](papers/completion/lean_refactor_arena/evidence/subgoal-ordering-pilot-2026-09-24/README.md)
completed with **zero shorter drafts in both arms**: baseline 304 primitive
attempts versus discharge 374, with 48 versus 42 queries. It used 15 native
processes and 375.3106 seconds, with no candidate screening/measurement or
promotion. All three original-proof controls passed. The option therefore
remains disabled by default. Its synthetic control successes do not establish
an Arena improvement. The linked report includes per-event regressions,
limitations of the trace, exact execution command and source/evidence hashes.

Changes in this slice:

- `jevops/lean/ArenaLocal.lean`: charged speculative discharge, full rollback,
  typed indexed paths, replayable goal rotation and V3 native receipts.
- `jevops/arena_local.py`: opt-in binding, strict receipt/path validation,
  unchanged independent script/term admission boundary.
- `jevops/arena_providers.py`: bounded ordering option in existing plans.
- `tools/run_local_premise_pilot.py`: two-arm matched ordering protocol.
- `tests/test_subgoal_ordering.py`, `tests/test_local_premise_pilot.py`: native,
  fixture, resource, forgery, compatibility and orchestration controls.
- README, this note and the linked evidence directory: commands and measured
  negative result. `arena_trial.py` also received the one-character syntax
  repair described below; its concurrently added policy was not changed.

## Observed validation (2026-09-24)

These commands were actually run against the working checkout, with test-seal
reuse disabled. This is a selected regression suite, not the full repository.

Focused offline: **220 passed, 31 skipped**, 1.82 seconds:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_subgoal_ordering.py tests/test_subgoal_retrieval.py \
  tests/test_local_premise_pilot.py tests/test_local_backward_search.py \
  tests/test_local_application.py tests/test_typed_premises.py tests/test_arena_trial.py
```

Expanded offline: **744 passed, 49 skipped, 9 deselected**, 11.22 seconds:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_subgoal_ordering.py tests/test_subgoal_retrieval.py \
  tests/test_local_backward_search.py tests/test_typed_premises.py \
  tests/test_local_application.py tests/test_arena_local.py \
  tests/test_local_premise_pilot.py tests/test_local_premise_replay.py \
  tests/test_local_tactic_portfolio.py tests/test_arena_premises.py \
  tests/test_arena_providers.py tests/test_premise_search.py tests/test_arena.py \
  tests/test_arena_trial.py tests/test_arena_pareto.py tests/test_refactor_prompts.py \
  tests/test_refactor_prompt_archives.py tests/test_scoped_proposals.py \
  -k 'not native_generated and not before_context_never_copies and not stale_capture_abstains and not native_admission'
```

Lean 4.26 new controls: **27 passed** (21 offline + six native), 70.17 seconds:

```bash
env JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_SEARCH_LEAN_TAG=v4.26.0 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider tests/test_subgoal_ordering.py
```

Lean 4.29 compatibility: **22 native passed, 107 deselected**, 244.73 seconds:

```bash
env JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_SEARCH_LEAN_TAG=v4.29.1 \
  JEVOPS_SIGNATURE_LEAN_TAG=v4.29.1 JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_subgoal_ordering.py tests/test_subgoal_retrieval.py \
  tests/test_local_backward_search.py tests/test_typed_premises.py -k native
```

An additional original subgoal-chain control passed on 4.26 (14.28 seconds)
after the native path representation change. Before the matrix, collection
temporarily failed on a concurrently edited `arena_trial.py` condition. The
only change made there was its missing closing parenthesis; its new
identical-source option and behavior were retained and its tests passed.
