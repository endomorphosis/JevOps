# Frozen mapped-premise injection experiments

`jevops.knowledge_trial` compares **local-only constructive search** with the
same search receiving explicit, scoped graph-to-library mappings. This is not
an isolated graph-structure ablation: one arm has extra premises and evidence
resolution work. It does not test a learned encoder, external claim fidelity,
autoencoder training, the all-15 Arena, or a global minimum.

The native controls and subsequent six-case smoke suite supply their declaration
mappings, including exact library-lemma names. They do not measure discovery of
those names from the goal. The [evaluation plan](KNOWLEDGE_GRAPH_PROOF_PLAN.md#separate-library-reuse-from-proof-discovery)
separates this supplied-mapping evidence from independent library retrieval and
composition/generalization, with distinct baselines and exclusions.

## API and gates

```python
from jevops.knowledge_trial import relation_trial_plan, run_relation_trial

inputs = dict(record=record, index=nominations, scope=scope, corpus=evidence,
              discovery_context=inventory_context, excluded_cids=protected_cids)
plan = relation_trial_plan(graph, **inputs, repetitions=2, seed=17)
# Save plan before executing. Verifiers must be fresh and prepared for every
# (VersionPin, branch_order); preparation/export needs its own process budget.
result = run_relation_trial(plan, graph, **inputs, verifiers=verifiers,
                            max_calls=plan["measurement_plan"]["planned_requests"])
```

### Opt-in structural rendering comparison

Pass `renderings=("local-term", "typed-inline", "inferred-term")` to freeze a v2
plan with three additional arms; the original reference, local-only and
fully typed mapped arms remain. Default plans still use the original arms.
No variant is selected after inspecting measurements.

- `local-term`: render the local-only proof as a direct term. This controls for
  savings from removing `by exact` without injecting mapped premises.
- `typed-inline`: replace mapped local leaves with the exact explicit declaration
  applications, retaining an expected-type ascription for each use.
- `inferred-term`: inline declarations and omit a supplied proposition-argument
  prefix only when all of its binders are implicit. Explicit parameters remain.
  The unchanged theorem must still elaborate and pass the kernel/axiom gate.

Constructive search now optionally exposes a small proof-term tree (local and
constant leaves, application, projection, lambda and pair), preserving its
existing search ranking and proof text. The renderer substitutes tree leaves,
not substrings, protects against binder capture and ambiguous global projections,
and enforces 4,096 unfolded nodes, depth 128 and 64 KiB rendered terms, followed
by the configured candidate-byte limit. Missing/oversized IR abstains rather
than falling back to unsafe text substitution. This is not a general Lean AST
parser or a completeness claim.

**Implicit inference is not a mapping certificate.** It can choose a different
instantiation from the graph's supplied arguments. Every compact mapped arm
therefore requires the original fully typed witness to pass on all scheduled
pin/order/repetition slots in the same fresh trial. An invalid, missing or
unmeasured witness blocks a graph-success/improvement claim even if the shorter
theorem itself compiles. Exact per-use mapping correspondence remains explicitly
unverified for `inferred-term`. All receipts, including those revealing this
distinction, are retained. The witness is part of the measured process budget,
not an unreported free helper declaration.

Both compact mapped arms are compared with **compact local** and with the old
**fully typed mapped** output using fresh observations from the same experiment.
These separate wrapper savings from premise-injection savings. There is still
no end-to-end runtime claim, training activation, automatic selection or
promotion of a winning variant.

The graph, inventory, source, scope, evidence, limits and implementation are
re-resolved before execution. All-pin discovery contexts are projected to
single-pin measurement contexts; only the selected pin/dependency and branch
order may differ. Changed imports, options, verifier code or missing pins fail
preflight. Native admission rechecks dependencies around every compiler call.
Artifacts and filesystem ownership remain trusted; no hostile concurrent-writer
or crash-resume guarantee is claimed.
Frozen-plan admission compares strict canonical JSON, so a saved/loaded plan's
tuple-to-array conversion is not mistaken for mutation. Actual changes to
sources, bounds, implementation identity or other fields still fail admission.

Both arms share `RelationLimits` search ceilings and one candidate slot. Actual
work is recorded by search-state counts, not claimed equal. An abstaining arm
uses the unchanged source, keeps its failure/abstention status, and is never
counted as a newly generated proof. Identical outputs are not cosmetically
changed to make them appear independent.

Measurement uses `arena_trial`: unchanged control plus two policies, both branch
orders, every required pin, and a seeded balanced schedule. Each observation
uses a fresh native process with receipt caching disabled. The policy-comparison
report compares mapped versus local, while original per-arm/reference results
remain available. Failed unchanged controls invalidate any improvement claim.
Rejections, timeouts and budget exhaustion are retained, not dropped from the
denominator. Passing fixture observations never claim native proof verification.

Token counts use the existing reference-compatible lexical tokenizer, including
all emitted `have` scaffolding. Heartbeats use raw native elaboration observations
per pin/order, not a fabricated scalar score. The existing conservative
separation/range rule requires at least two repetitions; it is not a statistical
significance test. Evidence ingestion and inventory export are not included in
proof-elaboration heartbeats. This is not an end-to-end cost measurement.

## Installed-core control pilot

The opt-in `test_native_library_relation_pilot` preregisters three controls:
`And.comm`, two `Or.inl` applications, and equivalence reversal. It uses existing
Lean 4.26.0 and 4.29.1 with an empty helper prefix, a synthetic SkillCenter-format
evidence corpus, and real exported library declarations persisted in DuckDB.
Its fixed ceiling is six inventory-export processes plus 72 proof measurements
(three cases × three arms × two pins × two orders × two repetitions).

Run with test sealing disabled, a **new** `--basetemp` under the existing capped
preparation volume, `JEVOPS_RELATION_TRIAL_NATIVE_TESTS=1`, `JEVOPS_ARENA_PREPARATION` pointing
to its existing `preparation.json`, and `JEVOPS_RELATION_TRIAL_RECEIPTS` naming a
new output directory. Run only
`tests/test_knowledge_trial.py::test_native_library_relation_pilot` for that pilot.
Set `TMPDIR` to the capped volume's existing scratch directory as well.
The control validates the existing volume and headroom; it never enlarges the
50 GB allowance, evicts caches, installs toolchains or restarts the watcher.
Keep the new basetemp directory to retain the source Parquet and DuckDB artifacts.

Additionally setting `JEVOPS_RELATION_RENDERING_TESTS=1` enables all three fixed
renderings. It predeclares 144 positive-case proof measurements and a 20-check
negative experiment, plus the same six inventory exports (**170 processes
maximum**). The negative experiment deliberately swaps the explicit arguments
to `And.comm`: the full witness must be rejected while the inferred term can
still pass. The graph gate must reject that apparent success. One repetition
suffices for this validity control; it makes no performance claim.

Designs, exact sources, full observations and compact Markdown summaries are
generated programmatically. The native test asserts validity and accounting,
**not that the mapped arm wins**. No result enables training or promotion.

## Retained control observations (2026-09-24)

The [generated summary](papers/completion/lean_refactor_arena/evidence/knowledge-relation-trial-2026-09-24/summary.md)
links the current interpretation to a frozen three-case run: all 72 proof
measurements verified, with six additional inventory-export processes. The
mapped policy produced more tokens than local-only search in all three cases.
`And.comm` used fewer heartbeats in both orders on both pins; the other two
cases regressed. None improved both measured axes. These controls support
investigating typed-obligation scaffolding minimization, not enabling training
or claiming a graph compression advantage.

Sibling JSON files retain exact plans, sources, contexts, raw observations and
DuckDB artifact identities. The source Parquet and DuckDB databases remain in
the run's retained basetemp directory on the existing capped preparation volume.
The expanded regression suite recorded **322 passed, 24 skipped**; the explicit
native pilot separately recorded **1 passed**. Skipped opt-in tests are not
reported as executed. No caches were evicted or allowance increased.

### Structural rendering pilot

The subsequent [generated rendering report](papers/completion/lean_refactor_arena/evidence/knowledge-relation-rendering-2026-09-24/summary.md)
retains all original arms and the three fixed rendering variants. Its 164 fresh
proof measurements produced 160 verifications and four deliberate rejections
of the wrong-instantiation witness, plus six inventory exports. All 144
positive-case observations verified. The negative control's inferred term did
compile, but failed the mandatory witness gate and received no graph-success
or improvement claim.

Inferred terms reduced the old mapped token counts from 28/64/29 to 1/8/5,
respectively, with fewer heartbeats in both orders on both pins. Against compact
local search, only `And.comm` reduced tokens as well as heartbeats; equivalence
reversal matched its token count with fewer heartbeats, and the Or-chain outputs
were byte-identical. The one-token proof is the already-imported library lemma
`_root_.And.comm`, checked against the full unchanged theorem statement—not an
omitted theorem, hidden helper, or empty proof.

Final regression validation recorded **350 passed, 24 skipped**. Additional
post-pilot capture/fallback guards and JSON-roundtrip admission fixes were
checked against the retained immutable artifacts: the
[canonical source-plan revalidation](papers/completion/lean_refactor_arena/evidence/knowledge-relation-rendering-2026-09-24/source-revalidation-canonical.json)
reproduced every measured source and plan value except implementation identity.
It supersedes an initial comparison that mistakenly distinguished tuples from
JSON arrays. Revalidation runs no compiler and does not renew native evidence;
the original observations remain bound to their recorded sources and contexts.
Stale implementation identities still require a newly frozen plan for execution.

This is a small development-control improvement, not an all-15 Arena score or
held-out generalization result. Broaden the fixed protected-canary evaluation
before any rule distillation or autoencoder training; training and promotion
remain disabled and all caches are retained within the existing allowance.

The [protected synthetic canary harness](KNOWLEDGE_RELATION_CANARIES.md) now
freezes six additional structural families, the primary rendering comparison,
and all bounds before observation. A retained DuckDB ledger prevents exposed
alpha-equivalent cases from being relabeled fresh, and every case remains in
the denominator. It is a post-development smoke test, not blind generalization
or permission to train on the evaluated cases.
