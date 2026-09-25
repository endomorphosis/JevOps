# Goal-only library-reuse control

This gate separates a valid short reference to a library theorem from a claim
that the system learned to compress or discovered a new proof. It supplements,
not replaces, the [supplied-mapping smoke tests](KNOWLEDGE_RELATION_CANARIES.md).
The earlier 66→1 comparison used a generated baseline; the retained original
reference has 57 lexical proof-body tokens. All three denominators must remain
distinct.

## Implemented boundary

[knowledge_lookup.py](jevops/knowledge_lookup.py) provides:

- `lookup_plan`: freezes the task, environment, immutable DuckDB snapshot,
  eligible pool, query, candidate orders, implementation identity and budgets.
  It accepts no solution-name list, reference-body query or hint override.
- `run_lookup`: uncached, all-pin native validation. Selection stops at the
  first valid candidate in each frozen order, not the most favorable observed
  heartbeat. Failures, resource gaps and work accounting stay in the report.
- `confirmation_plan` / `confirm_lookup`: fresh three-arm measurements of the
  original reference, direct scan and BM25 selection. Both branch orders and
  repeated measurements are mandatory for a paired improvement claim.
- `render_summary`: generates Markdown from the receipts. No model generates
  these reports. Discovery receipts are not reused as confirmation samples.

Both discovery policies use the **same full eligible inventory**, bounded to
64 declarations. Larger inventories fail before loading payloads; they are not
silently truncated. Scope filters cover the target, aliases, dependency
wrappers, missing dependencies and excluded provenance. Held-out rows cannot
enter the DuckDB index. Every candidate retains the exact theorem statement.

| Policy | Ordering | Application checked by Lean |
| --- | --- | --- |
| Direct scan | Deterministic declaration-name order | The frozen recipe set described below |
| BM25 | Sparse ranking from statement binders/type only | The same recipe set |

The default `application_mode="bare"` preserves the original bare-constant
search behavior. Opt-in `application_mode="bare-then-apply"` first tries all
bare constants in each policy's shortlist, then tries this existing primitive:

```lean
by solve | apply _root_.declaration <;> assumption
```

Lean can infer explicit parameters constrained by the goal; remaining argument
obligations must close using local hypotheses. Only one nominated lemma is
applied by the recipe. There is no recursive lemma search, `simp`, constructor
search, reference-proof replay or generated helper declaration. Inference and
typeclass synthesis still use the frozen environment: this is **not** a
checked-term dependency restriction for composition-only scoring.

The query excludes the theorem name, comments and reference proof. This is a
lexical signature extractor, **not** an elaborated AST. It does not rename local
variables into a canonical representation. Inventory metadata and provenance
remain trusted inputs; the API cannot prove its producer never saw the task.

This remains a bounded library-lookup baseline: it does not enumerate arbitrary
argument expressions, compose library lemmas or decide arbitrary semantic
equivalence. Neither `NO_DIRECT_MATCH_IN_SEARCHED_SET` (bare mode) nor
`NO_SUPPORTED_APPLICATION_IN_SEARCHED_SET` (extended mode) is a novelty
certificate. A valid multi-step proof can exist when both policies abstain.

`max_candidates` still caps **distinct declarations**, not recipes. Extended
mode reserves two recipes per declaration per pin before compilation. Reports
count checked recipes and distinct declarations separately; `whole_pool_exhausted`
requires every recipe for every eligible declaration to reach a terminal result.
Timeouts do not count as exhaustive negative evidence. BM25 has a separately
frozen `top_k`; shortlisting is part of the evaluated policy. Equal declaration
ceilings do not imply equal actual work. Verifier calls, native processes and
inventory exports also have separate accounting. No end-to-end speedup is
inferred from fewer native candidate checks alone.

New plans/receipts use schema v2 and bind the application mode, methods, order
and multiplied budgets. Historical v1 evidence stays unchanged; a code change
does not authorize reusing old receipts as fresh discovery or measurement.

## Admission and measurement

Every selected source must pass every required pin. A timeout, budget error or
missing environment is **incomplete**, not a semantic rejection. The native
boundary checks target absence before elaboration, unchanged theorem type,
kernel validity and transitive axiom policy in isolated reference/candidate
branches. All metric confirmation samples, including the original control,
must pass before the comparison is eligible.

The measurement uses `lra-reference-lexical/v1`: a qualified library identifier
is one lexical token. This is not one LLM tokenizer token, nor a one-node proof
tree including its dependencies. Both methods share the frozen library; no new
helper declaration or hidden generated proof body is added. Imported proof cost
and term size are not measured by the lexical count.

Identical one-token selections represent **1→1 versus library lookup**, even if
both greatly shorten the original reference. They cannot establish incremental
compression. Heartbeats are fresh command-elaboration measurements; they are
not retrieval time, precompiled-library build cost or statistical significance.
Fixture tests never acquire native authority. No results enable training,
promotion, canary reuse, watcher mutation or an official Arena score.

## Bounded installed-Lean regression

[test_knowledge_lookup_native.py](tests/test_knowledge_lookup_native.py) is opt-in
through `JEVOPS_KNOWLEDGE_LOOKUP_NATIVE_TESTS=1`. It requires the existing
`JEVOPS_ARENA_PREPARATION`, a new `JEVOPS_KNOWLEDGE_LOOKUP_RECEIPTS` directory,
`TMPDIR` on the capped volume and a fresh pytest `--basetemp` below that volume.
Run with `--test-seal=off`; never reuse an earlier pytest base directory.

The design is saved before discovery:

- First 64 line-start unannotated theorem names in installed Lean 4.26.0's
  `Init/PropLemmas.lean`, selected in source order. The source hash, extraction
  rule and full name list are retained. This is lexical nomination, followed by
  native declaration export on both pins—not source-regex proof authority.
- The already-exposed `and-or-distrib` task, unchanged. No supplied solution
  mapping enters the lookup query. The core-file choice was made after exposure,
  so **this is not blind corpus selection or a new random-canary evaluation**.
- Pins 4.26.0 and 4.29.1, top-k 8, candidate ceiling 64. At most 2 inventory
  exports, 144 discovery processes and 24 fresh confirmation processes.
- No downloads, dependency builds, LLM requests, training or exposure-ledger
  reset. Existing caches stay untouched. The fixed 50,000,000,000-byte allowance
  and storage reserve checks remain in force.

Reports are programmatically generated under the explicitly selected output
directory, including unsuccessful search results. The test does not require a
win and does not adjust the pool or ranking after seeing its outcomes.

The retained [2026-09-24 generated summary](papers/completion/lean_refactor_arena/evidence/knowledge-library-reuse-2026-09-24/summary.md)
links this design to [fresh discovery receipts](papers/completion/lean_refactor_arena/evidence/knowledge-library-reuse-2026-09-24/discovery.json),
[paired confirmation receipts](papers/completion/lean_refactor_arena/evidence/knowledge-library-reuse-2026-09-24/confirmation.json)
and [process/storage accounting](papers/completion/lean_refactor_arena/evidence/knowledge-library-reuse-2026-09-24/accounting.json).
It is exposed regression evidence only, with no training or official score.

## Explicit-argument capability controls

[test_knowledge_application_native.py](tests/test_knowledge_application_native.py)
has its own `JEVOPS_KNOWLEDGE_APPLICATION_NATIVE_TESTS=1` opt-in and a new
`JEVOPS_KNOWLEDGE_APPLICATION_RECEIPTS` output directory. Preparation, temporary
storage, fresh base directory and seal-off requirements are the same as above.

It freezes three hand-designed controls and a shared three-declaration pool:
an explicit proposition parameter, natural-number transitivity requiring two
local hypotheses, and a local implication chain requiring two applications.
The pool is task-matched and the references are already compact. These controls
test capability/abstention, **not blind retrieval or a compression advantage**.
The source goal is unchanged, and each selected proof needs both pins plus
fresh order-balanced confirmation. A confirmed reference fallback after search
failure is still an abstention, not a discovered composition.

The per-run ceiling is 6 native inventory exports, 72 discovery processes and
72 confirmation processes (150 total). No custom library prefix, downloads,
model calls, training, canary-ledger changes or cache eviction are allowed.
Native assertions require the expected capability, not a token or heartbeat
win. Programmatic summaries retain any regression versus the compact references.
Those application-control receipts measure the tactic source as-is. They are
not overwritten when a later materialization stage produces a compact term.

Retained [generated application-control report](papers/completion/lean_refactor_arena/evidence/knowledge-lemma-applications-2026-09-24/summary.md),
[frozen design](papers/completion/lean_refactor_arena/evidence/knowledge-lemma-applications-2026-09-24/design.json)
and [process/storage accounting](papers/completion/lean_refactor_arena/evidence/knowledge-lemma-applications-2026-09-24/accounting.json)
keep these capability checks separate from the earlier exposed library-reuse
regression. No previous receipts were replaced.

## Checked compact-term extraction

[knowledge_materialize.py](jevops/knowledge_materialize.py) adds a separate,
opt-in stage. `materialization_plan` freezes one policy (BM25 by default), its
selected one-lemma recipe, the full environment and both process allowances.
Saved discovery supplies **only a seed nomination**; this stage does not rerun
retrieval or count historical successes as fresh verification.

`run_materialization` first checks the seed on every required pin. It then uses
the existing `ArenaLocalRuntime` to capture **the generated application only**,
select the exact complete tactic span and reapply the nominated lemma from the
regenerated before-state. No nested after-state anchor or reference-proof body
is used to discover the term. Existing native local checks audit the closed
proof and replay its printed `exact ...` form from the original before-context.

Removing the `by exact` wrapper is a source transformation, not a proof rule.
The resulting whole theorem must independently pass the existing native
type/kernel/axiom boundary on every pin. Compact source must agree across pins
and be strictly shorter than the application. Missing/ambiguous anchors,
failed replay, different printed terms, unsupported source and non-shortening
results produce no admitted candidate. Local replay alone never grants
whole-source authority. Fixture injection cannot enter native mode.

`measurement_plan` and `measure_materialization` separately measure the unchanged
original, generated application and compact term with fresh processes, both
branch orders and repetitions. All three arms must pass. Improvements versus
the application and versus the original have **separate denominators**. Matching
a compact reference is not a new high score, learned compression or novelty.
When extraction abstains, unchanged fallbacks remain explicitly ineligible for
a discovered-proof reward even if those fallback proofs pass.

The opt-in [native extraction controls](tests/test_knowledge_materialize_native.py)
use `JEVOPS_KNOWLEDGE_MATERIALIZE_NATIVE_TESTS=1` and a new
`JEVOPS_KNOWLEDGE_MATERIALIZE_RECEIPTS` directory, with the same preparation,
capped temporary storage and seal-off requirements. They retain the previous
three hand-designed tasks. The two application seeds each reserve four local
capture/replay processes plus four whole-source checks. The abstaining task
reserves no extraction work. All three receive 24 separate measurement checks:
**88 native processes maximum**, no new inventory exports or retrieval runs.

No training, promotion, watcher restart, model call, download, dependency build,
exposure-ledger reset or cache eviction is part of this stage. Reports are
generated from receipts; neither a hash nor a saved printed term is proof
authority. General term minimization and independent blind evaluation remain
open work.

Retained [generated term-materialization report](papers/completion/lean_refactor_arena/evidence/knowledge-term-materialization-2026-09-24/summary.md),
[frozen seed design](papers/completion/lean_refactor_arena/evidence/knowledge-term-materialization-2026-09-24/design.json)
and [process/storage accounting](papers/completion/lean_refactor_arena/evidence/knowledge-term-materialization-2026-09-24/accounting.json)
separate tactic-overhead removal from improvements over the original compact
references. Historical lookup and application receipts remain unchanged.

## Incumbent-aware selection bridge

[knowledge_selection.py](jevops/knowledge_selection.py) connects a materialized
term nomination to the existing `arena_pareto` two-phase selector. It is an
opt-in Python API, not an activated watcher or training path:

```python
plan = compact_selection_plan(
    materialization, record=current_record, context=discovery_context,
    incumbent=current_incumbent,  # Candidate, or None for the original reference
)
result = run_compact_selection(
    plan, materialization, record=current_record, incumbent=current_incumbent,
    verifier_factory=fresh_verifiers,
    max_calls=plan["required_request_budget"],
)
```

The caller supplies the actual current record/incumbent separately from the
historical materialization. Changes to either invalidate the frozen plan. A
longer generated tactic cannot replace the original reference denominator.
No candidate, a token tie, or a token regression needs compiler work; these
paths explicitly leave `retained_incumbent_verified=False`. Skipping an
unpromising candidate is not a cached proof success.

Only strict token improvements over **both** original and incumbent reach
screening. The existing selector then requires lower raw heartbeats in every
version/order stratum, using its predeclared noise floor and observed-range
rule. It freezes one winner before new confirmation processes. Confirmation
cannot try another candidate or retry after failure. Identical original and
incumbent source bytes share a control; distinct sources are measured separately.
All phases must project the exact discovery environment. Missing bindings,
stale implementations, changed options and already-used guards fail closed.

Historical success flags, historical heartbeats and hashes provide no admission
authority. Native checking of the fixed theorem type and axioms is unchanged.
Fixture evidence cannot produce a native recommendation. A recommendation is
local evidence only: it does not promote source, emit training pairs, establish
novelty/generalization, or establish parity with official Arena worker metrics.

The [native admission controls](tests/test_knowledge_selection_native.py) use
`JEVOPS_KNOWLEDGE_SELECTION_NATIVE_TESTS=1` and a new
`JEVOPS_KNOWLEDGE_SELECTION_RECEIPTS` directory. As above, set
`JEVOPS_ARENA_PREPARATION`, use capped `TMPDIR` and a fresh pytest base directory,
and disable test seals. This run reserves at most 40 native processes: 16 for
screening and 24 for confirmation if eligible. It performs no extraction,
inventory exports, new retrieval, downloads, cache removal or model calls.

The retained [programmatic admission report](papers/completion/lean_refactor_arena/evidence/knowledge-compact-selection-2026-09-24/summary.md)
and [accounting](papers/completion/lean_refactor_arena/evidence/knowledge-compact-selection-2026-09-24/accounting.json)
show five zero-process decisions (two ties, two ties against the original despite
longer incumbents, one missing candidate). A deliberately forged one-token
nomination preserved the historical success claim and recomputed its hash;
all eight fresh native candidate checks rejected it, while all eight original
controls passed. No confirmation was needed, and no recommendation was issued.
These are exposed synthetic regression controls, not a positive native
improvement result, a blind benchmark or a new score. The positive two-phase
path is covered by explicitly labeled fixture tests and the existing selector
tests; the new bridge still needs real improving candidates.

## Next gates

This is not the all-15 Arena benchmark or a graph-structure ablation. Before
learning/generalization claims, add preregistered real-corpus inventories,
separately protected task families, broader argument-term search and
materialization controls, and checked-term dependency exclusions for the
composition-only track. Then
compare graph vs no-graph policies receiving the same retrieved premises.
Unknown equivalence or unsupported detectors must remain unknown.
