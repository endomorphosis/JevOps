# Native application and explicit-proof materialization

This is the first bounded implementation slice of the
[September research plan](LEAN_REFACTOR_ARENA_RESEARCH_PLAN_2026_09_24.md).
It extends the existing Arena provider, project-context replay runtime and Lean
replay checker. It introduces no agent framework, model dependency, training,
daemon, download or build requirement for offline tests.

`baseline-v1` and `portfolio-v1` retain their existing behavior. The new path is
an explicit `ArenaLocalRuntime.discover_batch(...)` call. It does not make the
offline provider CLI launch Lean implicitly.

## What is implemented

1. `plan_local_applications` validates the existing source/capture/environment
   and scoped premise inventory. It nominates bounded `(event, premise)` pairs.
   Target aliases, dependent wrappers, held-out declarations and unavailable
   names retain the existing exclusions. Inventory scanning still fails closed
   on overflow; lexical scores are not assertions of applicability.
2. Select supported single-goal closing spans by `headroom-v1` (descending span
   tokens), or `smallest-v1` (the historical ascending byte-length order). Span
   tokens use the Arena lexical tokenizer. This is a heuristic, not a predicted
   heartbeat cost, minimum proof size or dependency analysis. Synthetic branch
   headers and declaration/`by` wrappers cannot become edits.
3. Round-robin over selected spans' nominations. For each, regenerate the native
   before-context and try exactly `solve | apply _root_.NAME <;> assumption`.
   Lean does conclusion unification and argument inference. **Every generated
   subgoal must close**; a relevant-looking name or an applicable but incomplete
   rule is not a proof. There is no recursive search or forward chaining yet.
4. Check the instantiated proof against the original goal telescope in Lean's
   kernel and audit dependencies against the existing standard-axiom policy.
   Extract the proposed proof expression from this search, never from the
   captured reference's after-state. Delaborate it to `exact TERM` with full
   names and visible proofs.
5. Independently parse and replay the printed term from a fresh copy of the
   original before-context. Check type and axioms again. Pretty-printer output
   is a proposal, not a faithful proof serialization by assumption.
6. Only now apply the strictly-shorter final-source filter and source deduplication.
   Return ordinary four-field Arena drafts for independent all-pin verification
   and the existing measurement/confirmation selector.

The discovery script is allowed to be longer than the source region. A control
uses `exact Or.inl (id h)` as the original region; the longer guarded application
can produce the shorter `exact library_step h`. The library declaration itself
is fixed in the original prefix, not introduced or moved outside the charged
candidate body by this refactor.

## Trust and limits

- Only the existing injected `NativeLeanVerifier` supplies project bindings,
  executable pins, dependency fingerprints, timeout/heartbeat options and
  optional isolation. The default remains trusted-local execution, not an OS
  sandbox. Candidate metaprograms and producer honesty retain the limitations
  described in [the native verifier guide](ARENA_NATIVE_VERIFIER.md).
- Native applicability is checked after nomination. This initial slice used
  lexical retrieval; the subsequent [typed-premise slice](ARENA_TYPED_PREMISES.md)
  adds opt-in raw native head/telescope features. Generic/forward lemmas can be
  missed by retrieval; `NO_CONSTANTS` currently has no library nominations.
- Default plan limits: 16 spans, four premises per span, 16 applications, eight
  final drafts, 256 query nodes and 512 scanned inventory entries. Application
  caps accept 0–64; the runtime's independent integer process allowance may be
  lower. Zero is exhausted. `top_k`, event and query caps retain provider bounds.
- One application reservation includes one fresh process, baseline replay, at
  most one guarded application, delaboration and at most one extracted-term
  replay. `application_attempts` counts charged attempted application processes,
  including infrastructure failures; it is not a count of successful rule uses.
  Reported roundtrips count validated returned attempts; an aborted process may
  have done unreported internal work. These are not measured heartbeat savings.
- No cache, retries or refunds. A subsequent explicit call consumes another
  budget unit. Duplicate source results cannot create duplicate drafts, but the
  work actually performed to discover a duplicate remains charged.
- Python never evaluates generated expressions. Declaration names are bounded
  identifiers; native output is byte-bounded and extracted tactics are limited
  to 4,096 bytes. The plan retains at most 1 MiB of ranking JSON. Batch reports
  retain bounded outcome summaries and receipt content hashes instead of copying
  complete event snapshots into every attempt. Direct application calls return
  the full local receipt for callers that explicitly archive it.
- Captures bind exact source, context, pin, driver and budgets. This changes the
  exporter implementation identity: **recapture old observations** rather than
  rewriting their hashes to reuse them. Changing policy order does not establish
  compatibility of old verification evidence.
- A failed application is not a false proposition. No checked closure produces
  `NO_CHECKED_CLOSURE`; transport/protocol failures produce `ERROR`; exhausted
  process allowance produces `BUDGET_EXHAUSTED`. A batch can retain earlier
  drafts while reporting an incomplete/error tail. A plan's `truncated` flag
  records bounded coverage, not theorem failure.
- Injected runner fixtures are labelled `fixture`, emit `FIXTURE_DRAFTS_ONLY`,
  and do not count as native calls. Even live local success retains
  `proof_admitted=false`, `whole_source_checked=false` and
  `fresh_verification_required=true`.

The stronger final contract is unchanged: same statement/imports/dependencies,
fresh all-pin source checks, applicable axiom policy, cost comparison against
reference and incumbent, then fixed-winner confirmation. This increment does
not close documented source/export/measurement-integrity gaps or enable
production promotion.

## Existing harness integration

With a fresh project capture and scoped inventory from the existing adapters:

```python
from jevops.arena_local import ArenaLocalRuntime

runtime = ArenaLocalRuntime(guard, record, max_processes=17)
observed = runtime.capture(pin)
assert observed["ok"]
batch = runtime.discover_batch(
    pin, observed["capture"], index, scope,
    max_applications=16, cap=8, span_order="headroom-v1",
)
# batch["drafts"]: name/label/source/provenance records for the existing selector.
# Neither the batch nor a local replay authorizes promotion.
```

To optimize an incumbent, supply its existing `Candidate` as `seed` and capture
that exact source with `runtime.capture(pin, source=seed.source)`. Final token
filtering compares against the seed; the all-pin selector must still compare
against both original and incumbent. Never reuse offsets after applying edits.

## Reproducible control

Plan only, with no Lean invocation:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python papers/completion/lean_refactor_arena/tools/run_local_application_control.py
```

Explicit execution on already-installed pins, one process at a time:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python papers/completion/lean_refactor_arena/tools/run_local_application_control.py \
  --execute --tags v4.26.0 v4.29.1 --max-processes 8 \
  --output /tmp/jevops-application-control.json
```

Output files must not already exist. This reserves capture + application +
reference verification + extracted-source verification for each pin. All pins
share one immutable context. Baseline drafts are recorded as unverified
proposals, not a measured control arm. The script emits exact native receipts,
source token counts and total process/wall accounting; official score and API
cost stay null. This is a synthetic mechanism control, **not** a matched Arena
benchmark, strict-dual winner, latency estimate for a model or generalization
result. No new toolchains or project dependencies are provisioned.

## Tests

Offline protocol/planning/budget controls (no native opt-in):

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --test-seal=off tests/test_local_application.py
```

Native conjunction, missing-premise, wrong-conclusion, forbidden-axiom,
typeclass, definitional-equality and shadowing controls:

```bash
env JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_APPLICATION_LEAN_TAG=v4.26.0 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --test-seal=off tests/test_local_application.py -k native
```

Repeat with `JEVOPS_APPLICATION_LEAN_TAG=v4.29.1`. These tests require the named
installed executable and never install it. Outcome summaries and actual observed
run results are recorded separately from the commands above.

## Observed results, 2026-09-24

The [retained native control report](papers/completion/lean_refactor_arena/evidence/application-materialization-control-2026-09-24.json)
completed with `CONTROL_PASSED`: **eight native processes, 20.4318 seconds**,
no model calls, no promotion and no official score. Both 4.26.0 and 4.29.1 emitted
the same `exact library_step h` source, reducing this synthetic proof from
**7 to 4 Arena source tokens**, and independently verified the complete source.
The original, searched and materialized local proofs all passed the existing
kernel/type/standard-axiom checks. The archived heartbeat observations are
single-order screening data, not order-balanced confirmed performance gains.

The expanded offline integration suite passed **625 tests**, skipped 27 opt-in
native cases and deselected nine older auto-native cases in **9.89 seconds**:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_local_application.py tests/test_arena_local.py tests/test_local_premise_pilot.py \
  tests/test_local_premise_replay.py tests/test_local_tactic_portfolio.py \
  tests/test_arena_premises.py tests/test_arena_providers.py tests/test_premise_search.py \
  tests/test_arena.py tests/test_arena_trial.py tests/test_arena_pareto.py \
  tests/test_refactor_prompts.py tests/test_refactor_prompt_archives.py tests/test_scoped_proposals.py \
  -k 'not native_generated and not before_context_never_copies and not stale_capture_abstains and not native_admission'
```

The nine explicit application controls passed on 4.29.1 in **86.93 seconds**
(36 offline controls deselected), using the native command above with the tag
changed. An earlier run of the eight application controls on 4.26.0 plus the
existing project-local tests selected by `-k native` passed **22 checks** in
**109.31 seconds**: eight new native controls, four existing native checks on
4.26.0/4.34.0, and ten offline native-envelope corruption checks. That earlier
run preceded addition of the ninth application rollback control.

The shared exporter/replay regression suite also passed **80 tests in 57.49
seconds**, including forged goal closure, hidden axioms, shared unresolved
metavariables and stale-context controls, on the explicitly selected installed
4.26.0 executable:

```bash
env PATH=/home/barberb/.elan/toolchains/leanprover--lean4---v4.26.0/bin:$PATH \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --test-seal=off tests/test_proof_replay.py tests/test_proof_state.py
```

Use your own installed toolchain's `bin` directory for that explicit `PATH`.

This is focused integration coverage, not a claim that the entire dirty checkout
or full Arena corpus has been evaluated. Pre-existing work was preserved.

## Next experiment, not yet a result

The first real-corpus trial should hold task/pin sets and total discovery,
screening and confirmation ceilings fixed. Compare smallest/headroom selection
and lexical-draft/native-application paths separately. Charge the new path's
additional discovery work; matching final draft counts alone is not matched
compute. Freeze inputs, use isolated memory, report all failures and keep known
warmup incumbents distinct from new wins. The subsequent typed-premise slice
adds the signature index and a two-arm retrieval pilot. The full 2×2 experiment,
multi-step search, support minimization and coupled repair remain pending.
