# Scoped retrieval during backward proof construction

This implements the next slice after the [bounded backward-search trial](papers/completion/lean_refactor_arena/evidence/bounded-search-pilot-2026-09-24/README.md).
That trial constructed partial chains but failed to close all premises; its
four root-goal nominees were reused unchanged for every descendant. The new
mode can retrieve other **already admitted-to-inventory** declarations for a
new subgoal. Inventory admission means available/scope-checked, not that a
retrieved declaration proves the current goal.

No new dependencies, model calls, proof authority or parallel agent framework
are introduced. Old defaults and fixed-pool V1 receipts remain supported.

## Implementation and use

```python
batch = runtime.discover_batch(
    pin, capture, index, scope,
    retrieval="typed-head-v1", span_order="matching-head-v1",
    search="subgoal-v1", max_pool=64, max_retrievals=32, retrieval_top_k=4,
    max_steps=96, max_depth=4, max_events=64, max_applications=4, cap=1,
)
```

The existing native inventory exporter must still check declarations, dependency
and axiom policies against every required pin. `PremiseIndex.scoped_pool` uses
the **same** exclusion implementation as `rank`: unavailable names/dependencies,
protected target aliases, their transitive wrappers, held-out splits and excluded
origins stay out. The planner also excludes both Arena target and source theorem
names. It does not restrict the pool to names matching the root's lexical query.

Pool setup scans the explicit index (at most 8,192 entries), propagates exclusions
and emits at most 64 canonical `{name, head}` records. It records setup scan and
exclusion counts. If too many names qualify, it abstains with `POOL_BUDGET` and
no prefix of the pool; it never silently truncates scope by insertion order.
Missing/nonconstant signatures retain a `null` head and may enter fallback.

Within the native search process:

1. Keep the original shortlist/actions at depth zero, so the new mode changes
   descendant retrieval rather than initial span selection.
2. For a newly visited descendant, inspect at most 256 nodes of the **current**
   goal's application/metadata/assigned-metavariable head spine. This does not
   normalize the goal, inspect local proof values or scan the Lean environment.
3. Query an in-memory conclusion-head index built once from the explicit pool.
   Prefer exact constant heads; within a tier retain root-shortlist priority,
   then canonical pool order. Reserve one fallback slot when top-k permits it.
   Unknown heads use fallback. Up to eight names may be returned per query.
4. Perform the existing native AND/OR proof search: assumption, scoped `apply`,
   intro and constructor, with whole elaborator-state restoration on failure.
   All generated premises and siblings must close. A matching head or successful
   application alone does not establish the target.
5. Replay the successful primitive script, check the closed proof against the
   original goal/environment and axiom policy, print its term, and independently
   replay that printed term before applying the existing shortening filter.

The original environment remains authoritative. Raw head features are hints;
even dishonest features can only change the search, not bypass kernel checks.
Only fresh whole-source checks on **every required pin**, cost checks, and
separate confirmation can support a promoted improvement.

### Files and compatibility

- `jevops/premise_search.py`: shared exclusions, bounded scoped pool and the
  deterministic selection function used to check native receipts.
- `jevops/arena_providers.py`: opt-in `subgoal-v1` plans and bound pool/query
  limits; root ranking and historical modes stay unchanged.
- `jevops/lean/ArenaLocal.lean`: indexed current-subgoal reads, explicit traces,
  non-refundable query accounting and unchanged native proof admission path.
- `jevops/arena_local.py`: validates V2 search receipts and charges, while keeping
  V1 fixed-pool reports. The adapter identity now also binds the premise helper
  source; old captures require their original frozen implementation, or a new
  capture epoch under this implementation.
- `tools/run_local_premise_pilot.py`: a three-arm frozen comparison inside the
  existing project/control/screen/measurement harness.
- `tests/test_subgoal_retrieval.py` and `tests/test_local_premise_pilot.py`:
  protocol, exclusion, resource, native construction and orchestration controls.

Low-level `discover_search(..., subgoal_pool=..., max_retrievals=...,
retrieval_top_k=...)` takes a **trusted caller's** scoped pool. Use `discover_batch`
for the planner's split/dependency/target filtering. No ambient clients or
global mutable retrieval state are added.

## Trace, budgets and failure meanings

V2 search reports bind the exact pool, ordered initial shortlist, context,
capture/source, pin, depth/step limits and retrieval settings. Each query records
its sequential ID, depth, observed head and selected names; each primitive action
records which query supplied its permitted names (`null` means the root shortlist).
The Python boundary reconstructs selections, rejects out-of-pool or unqueried
actions, and checks script/term replay receipts. Fixture reports are explicitly
fixtures, not native verification evidence.

Primitive attempts remain capped at 256 per process, depth at eight. Queries are
capped at 256 (default 32), pool size at 64 and query top-k at eight (default four).
The parser validates bounds and names on both sides. Zero pool/query allowance
disables the mode before launch; zero is never replaced by a default. Pool
overflow also launches no native search process.

`retrievals_reserved` is the non-refundable query allowance for launched
processes; `retrievals_observed` counts completed native query traces. Backtracking
restores Lean state, **not** query or primitive counters. Revisited goals are
charged again; there is no hidden cache. A timeout retains its reservation and
has unknown internal work, not a fabricated zero. Separate query and step
exhaustion flags make finite-budget abstentions inspectable.

Head lookup and fallback touch only the explicit pool; fallback processing is
bounded by 64 entries. Index/scope preparation, capture and dependency
fingerprinting remain setup work, not claims of whole-system locality. Existing
deadline/output caps bound the process. Lean heartbeat settings apply to its
separately initialized phases and are **not** aggregate process-cost measures.

`ABSTAINED` means no checked shorter draft under this search/configuration;
`BUDGET_EXHAUSTED` before launch means the configured work cannot proceed;
`ERROR` means invalid evidence or infrastructure failure. None disproves the
theorem. Neither a cache/content hash nor a partial search path is a proof.

## Offline and native controls

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_subgoal_retrieval.py tests/test_local_premise_pilot.py \
  tests/test_premise_search.py tests/test_local_backward_search.py \
  tests/test_local_application.py tests/test_typed_premises.py

env JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_SEARCH_LEAN_TAG=v4.26.0 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_subgoal_retrieval.py -k native
```

Native tests require only already-installed toolchains; they do not download
Lean or call a model. The positive control starts with only `finish` and discovers
`bridge` for the new `Middle` goal, then discharges `Seed` by assumption:
`finish (bridge h)`. The same fixed-shortlist search cannot close it under the
same tactic budget. The resulting shorter source passes a fresh whole-source
check. This synthetic control is not an Arena score improvement.

Other controls cover conjunction, bad-branch rollback, exact/zero query budgets,
missing premises, misleading heads, forbidden axioms, foreign/forged traces,
scope/alias/held-out leakage and bounded pool overflow. No tests claim exhaustive
proof search or calibrated neural confidence.

Observed test results on this implementation:

- Focused offline command above: **170 passed, 25 skipped**, 1.53 seconds.
- Seven new native controls on Lean 4.26.0: **7 passed**, 70.52 seconds.
- New controls plus fixed-search and typed-retrieval native regressions on Lean
  4.29.1: **16 passed**, 166.19 seconds.
- Expanded selected offline regression: **720 passed, 43 skipped, 9 deselected**,
  11.03 seconds. This is not a claim that the entire repository suite was run.

Exact additional commands:

```bash
env JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_SEARCH_LEAN_TAG=v4.29.1 \
  JEVOPS_SIGNATURE_LEAN_TAG=v4.29.1 JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_subgoal_retrieval.py tests/test_local_backward_search.py \
  tests/test_typed_premises.py -k native

env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_subgoal_retrieval.py tests/test_local_backward_search.py \
  tests/test_typed_premises.py tests/test_local_application.py tests/test_arena_local.py \
  tests/test_local_premise_pilot.py tests/test_local_premise_replay.py \
  tests/test_local_tactic_portfolio.py tests/test_arena_premises.py tests/test_arena_providers.py \
  tests/test_premise_search.py tests/test_arena.py tests/test_arena_trial.py tests/test_arena_pareto.py \
  tests/test_refactor_prompts.py tests/test_refactor_prompt_archives.py tests/test_scoped_proposals.py \
  -k 'not native_generated and not before_context_never_copies and not stale_capture_abstains and not native_admission'
```

The deselections exclude older automatically native cases from the offline run.

## Frozen real-task comparison

Plan-only (offline, no native launches):

```bash
python papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py \
  --comparison subgoal-retrieval --cap 1 --max-processes 76 \
  --nominees papers/completion/lean_refactor_arena/evidence/local-premise-core-nominees.json
```

| Arm | Descendant premises | Maximum depth | Primitive ceiling/process |
| --- | --- | --- | --- |
| `fixed` | Root shortlist | 4 | 96 |
| `subgoal` | Current-head retrieval | 4 | 96 |
| `deeper` | Same current-head retrieval | 8 | 96 |

Each arm gets four discovery processes and one final draft slot. All share the
same frozen capture, all-pin inventory, span order, initial top-k, controls,
screening and measurement protocol. Each dynamic arm separately reserves up to
128 retrievals. The first comparison isolates retrieval; the second changes
only depth. Primitive/process **ceilings** are matched, not actual work, query
overhead, aggregate heartbeats or wall time. Rewriting is deliberately absent.

Execution requires the existing read-only source snapshot, manifest identity,
prepared project/nominee inputs, capped 50 GB preparation volume and exclusive
build lock. There is no provisioning, resumption or automatic promotion in this
protocol. Only shorter independently replayed drafts reach fresh all-pin source
screens; only surviving candidates reach measurement. This remains exploratory
reference-informed public warmup, not held-out model evaluation.

The [completed frozen trial](papers/completion/lean_refactor_arena/evidence/subgoal-retrieval-pilot-2026-09-24/README.md)
used 19 native processes and 503.1259 seconds. All three original controls
verified, but all arms produced zero shorter drafts. Dynamic retrieval found
and applied the three previously missing intermediate lemmas on the promising
span; nested premise expansion and finite search limits still prevented closure.
The depth-8 arm did more primitive work without producing a complete proof.
No query allowance was exhausted. There was no candidate measurement or
promotion and **no demonstrated Arena score improvement**.

## Remaining limits

The pool is finite and user-selected. Retrieval does not discover names outside
that pool, rewrite nonmatching arguments, normalize type synonyms, mine local
hypothesis function bodies, or train a retriever. A raw head can prioritize an
inapplicable lemma. Depth-first search may spend its budget on an unhelpful
branch, and deterministic assumption/constructor choices are not exhaustive.
Repeated queries have no memoization or cycle pruning beyond finite limits.
Future normalization or search-order changes need their own scoped actions,
accounting, native replay and controlled ablations.
