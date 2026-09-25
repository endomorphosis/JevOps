# Bounded backward construction and span selection

This is the next implemented slice of the [research plan](LEAN_REFACTOR_ARENA_RESEARCH_PLAN_2026_09_24.md).
It extends the existing `ArenaLocalRuntime`, premise planner and native Lean driver.
There is no second agent framework, model download, API call or new dependency.

The [previous typed-retrieval pilot](papers/completion/lean_refactor_arena/evidence/typed-premise-pilot-2026-09-24/README.md)
produced no shorter drafts: its four attempts visited the same large compound
goals even though typed retrieval changed nominations on fourteen other spans.
This increment addresses both span allocation and proof construction. Neither
an equal expression head nor a large source span is evidence of applicability.

## Opt-in behavior

```python
batch = runtime.discover_batch(
    pin, capture, index, scope,
    retrieval="typed-head-v1", span_order="matching-head-v1",
    search="backward-v1", max_steps=96, max_depth=4,
    max_events=64, top_k=4, max_applications=4, cap=1,
)
```

The existing all-pin native inventory/scope and current source-bound capture
are required. Nothing here bypasses their target, alias, held-out or dependency
exclusions. Low-level `discover_search` accepts explicit premises from its
trusted caller; use the batch API for inventory/split filtering.

`matching-head-v1` first observes at most `max_events` spans in descending
source-token order, using the existing bounded queries and rankings. Among
those observations it prioritizes spans with at least three source tokens and
an exact constant-head nominee. After three preferred spans it services one
fallback span, while either queue remains. Smaller or mismatched spans are not
permanently removed, but finite observation/top-k/process limits still omit
work. This is a heuristic, not unification or a completeness/fairness theorem.

`backward-v1` sends one bounded list of scoped nominees per selected span to
Lean. The existing one-step method remains `apply-assumption-v1`; all old
defaults, inventory schemas and old planner request identities are unchanged.

## Native symbolic computation

The driver performs depth-first AND/OR search in a regenerated **before** context:

1. Try `assumption`, then the explicit fully qualified lemma applications, then
   `intro` and `constructor`. No library-wide hidden search or arbitrary tactic
   fragments enter through the premise list.
2. Native `apply` performs unification and creates actual metavariable goals.
   Every generated premise and every sibling must close. A successful lemma
   application by itself is not success.
3. Save Lean's full tactic/term elaboration state before each alternative and
   restore it (including information state) on failure. Failure of a later
   sibling can backtrack choices made for an earlier sibling. The attempt
   counter lives outside this restorable state and cannot be refunded.
4. A discovered path is just a proposal. Serialize its primitive actions as
   a bounded `solve | (focus (...)); ...` script, then run the existing
   application/materialization boundary again from the original context.
5. That boundary checks the original baseline, executes the proposed script,
   checks the closed proof against the original environment and expected type,
   audits permitted axioms, prints an explicit `exact ...` term, and replays
   the printed term independently from the original context.

Only independently replayed terms can become drafts, and only when replacing
the exact span strictly reduces Arena source tokens. Fresh **whole-source checks
on every required pin**, cost measurement and separate confirmation remain
necessary. A local result is never `proof_admitted` or `whole_source_checked`.

## Resource and evidence accounting

- At most eight premise names, depth eight, and 256 primitive attempts per
  search process; defaults are depth four and 96 attempts. Zero disables work,
  not a request to use defaults. Boolean/fractional/negative limits are rejected.
- Each primitive is reserved before execution, whether it succeeds or fails.
  Depth applies to each goal's proof branch; other siblings retain their own
  depth. Cyclic applications terminate at the depth/step boundary.
- A process reservation covers search, successful-path replay and term replay.
  `search_steps_reserved` is the conservative non-refundable primitive allowance;
  `search_steps_observed` counts primitive invocations in completed reports.
  Those counts do **not** include work in the independent script/term replays.
  Existing deadline and output limits cover the whole process. Lean's heartbeat
  option applies within its separately initialized phases; it is not an aggregate
  primitive counter or a measured whole-process cost.
- `application_attempts` in a search batch counts observed native `apply`
  invocations, not processes. `attempted_processes` remains a separate counter.
  Infrastructure failures have unknown observed internal work; the batch retains
  the reservation and reports `unknown_search_processes`. No refund or retry.
- Search receipts bind context, source/capture, pin, ordered nominees and limits.
  Validators reject unauthorized actions, mismatched counts/limits, scripts not
  reconstructed from the reported path, stale captures and invalid replay/axiom
  receipts. A content hash binds a record; it is not a proof.
- The bounded trace records primitive action, depth and whether the action
  applied. An `applied` entry can belong to a subsequently failed branch.
  `step_exhausted`, `depth_cutoffs`, `path` and replay outcomes remain distinct.

No path means bounded abstention, not that the theorem is false. Missing native
infrastructure is an error, not semantic rejection. Fixture runners retain their
explicit fixture label and cannot constitute native verification evidence.

## Reproduction and comparison

Plan-only, offline (no compiler resolution or process launch):

```bash
python papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py \
  --comparison bounded-search --cap 1 --max-processes 76 \
  --nominees papers/completion/lean_refactor_arena/evidence/local-premise-core-nominees.json
```

The public three-pin `Core.InitsUpdatesComm` protocol has a maximum of 76 native
processes: 19 discovery/control, 9 whole-source screens and 48 measurement
processes. Unused stages are not launched. A full reservation is required before
execution. Execution additionally requires `--execute`, a reviewed source
snapshot and its manifest hash, prepared project/nominee inputs inside that
snapshot, the existing capped preparation volume/exclusive-build lock, installed
toolchains and a fresh output directory. No new project builds are performed.

The three arms share the same capture, typed all-pin inventory, four discovery
processes per arm, final draft limit, source checks and measurement protocol:

| Arm | Span order | Construction |
| --- | --- | --- |
| `headroom` | Largest source-token spans first | One lemma, discharge by assumption |
| `matching` | Matching-head priority with fallback | Same one-step operation |
| `backward` | Same matching-head schedule | Bounded multi-step AND/OR search |

The first comparison isolates span selection; the second changes construction.
Process/deadline ceilings and the per-phase Lean heartbeat setting are matched,
**not aggregate heartbeat work, primitive work or measured wall time**. The
backward arm reserves at most 384 primitive search attempts;
do not call extra internal search free. Discovery order is predeclared and serial.
Only surviving all-pin drafts reach measurement. No automatic promotion or
official score is produced; this is reference-informed exploratory warmup, not
a held-out evaluation.

Focused offline tests:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --test-seal=off -p no:cacheprovider \
  tests/test_local_backward_search.py tests/test_local_premise_pilot.py \
  tests/test_local_application.py tests/test_typed_premises.py
```

Native controls (explicit opt-in; already-installed Lean only):

```bash
env JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_SEARCH_LEAN_TAG=v4.26.0 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --test-seal=off -p no:cacheprovider \
  tests/test_local_backward_search.py -k native
```

Observed during implementation: 107 focused offline tests passed (18 native
cases skipped), followed by an additional periodic-fallback regression. The final
broader selected offline regression suite passed **683 tests** in 10.36 seconds
(36 skipped, 9 deselected). All eight native search controls passed on Lean
4.26.0 in 80.21 seconds, including chains, conjunction, intro, bad-branch rollback,
cycles, step/depth exhaustion and forbidden-axiom rejection. On Lean 4.29.1,
the eight search, nine legacy application and one typed-retrieval native controls
all passed (18 tests, 189.60 seconds). The synthetic chain
requires two applications and yields a shorter, freshly whole-source-checked
proof; the single-application baseline fails to close it. These are control
results, not an Arena score increase.

Exact expanded regression commands:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_local_backward_search.py tests/test_typed_premises.py \
  tests/test_local_application.py tests/test_arena_local.py \
  tests/test_local_premise_pilot.py tests/test_local_premise_replay.py \
  tests/test_local_tactic_portfolio.py tests/test_arena_premises.py \
  tests/test_arena_providers.py tests/test_premise_search.py tests/test_arena.py \
  tests/test_arena_trial.py tests/test_arena_pareto.py tests/test_refactor_prompts.py \
  tests/test_refactor_prompt_archives.py tests/test_scoped_proposals.py \
  -k 'not native_generated and not before_context_never_copies and not stale_capture_abstains and not native_admission'

env JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_SEARCH_LEAN_TAG=v4.29.1 \
  JEVOPS_APPLICATION_LEAN_TAG=v4.29.1 JEVOPS_SIGNATURE_LEAN_TAG=v4.29.1 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_local_backward_search.py tests/test_local_application.py \
  tests/test_typed_premises.py -k native
```

The explicit deselections avoid older auto-native cases in the offline run.
These are selected regression suites, not a claim that the whole repository's
test suite was run.

The [frozen Strata trial](papers/completion/lean_refactor_arena/evidence/bounded-search-pilot-2026-09-24/README.md)
has now completed: all three original controls verified; all three arms produced
zero shorter drafts. It used 19 native processes and 573.7201 seconds, with no
candidate measurement, confirmation or promotion. Span selection changed the
attempted regions; backward search made partial multi-lemma progress but did not
close all premises. The retained trace identifies fixed intermediate-premise
coverage, argument normalization and finite depth/step limits as next issues to
test. There is **no demonstrated Arena score improvement** from this pilot.

## Limits

Search is deliberately incomplete: it has no best-first scheduler, forward
saturation, equality saturation, learned policy, proof cache or general tactic
portfolio. `assumption` and `constructor` use their native deterministic choices;
the search does not enumerate all possible matching locals or constructors.
Finite scope/top-k/depth/step limits can miss a proof. A first found path may be
larger than another valid proof, or fail later audit/printing; there is no hidden
retry to optimize it. Open/shared-metavariable local telescopes retain the
existing replay abstention behavior. Trusted-local metaprogram execution and
the existing optional isolation boundary are unchanged.
