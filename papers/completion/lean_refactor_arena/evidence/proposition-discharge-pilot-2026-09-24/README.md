# Proposition-discharge pilot: diagnosis confirmed, no shorter refactor

Historical exploratory evidence, not an admission cache or official score.
[Implementation, limits and exact test commands](../../../../../ARENA_PROPOSITION_DISCHARGE.md).

## Matched protocol and observed result

Public warmup `Core.InitsUpdatesComm`, original 224 Arena tokens. Original-proof
controls verified on Lean 4.29.1, 4.27.0 and 4.26.0. All arms share one fresh
37-event capture and an eight-lemma all-pin inventory. Nominees are
reference-informed, not held-out. All select events **13, 14, 17, 2**.

Each arm uses dynamic subgoal retrieval, initial/subgoal top-k four, depth eight,
96 primitive attempts and 32 queries per invocation, four search invocations
and one shorter-draft slot. The two observed arms both use a window of eight
and 256 goal-kind inspections per invocation; they differ only by the filter.
Baseline has no inspection work. Process/primitive/query ceilings are matched;
actual work and baseline inspection overhead are not.

| Arm | Primitives | `apply` attempts | Queries | Inspections | Skips | Shorter drafts | Discovery seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 304 | 172 | 48 | 0 | 0 | 0 | 103.4025 |
| Observe all | 374 | 151 | 42 | 156 | 0 | 0 | 100.2626 |
| Proposition-only | 349 | 126 | 47 | 310 | 135 | 0 | 99.8729 |

**No shorter refactor was found in any arm.** Filtering reduced primitive work
by 25 versus unrestricted discharge (6.7%), but added 154 inspections and five
queries, while still using 45 more primitives than baseline (14.8%). These
different kinds of units are not interchangeable. This does **not** establish
an efficiency improvement. Single serial-run wall times are not a statistically
meaningful speedup comparison; setup/import/cache effects are not isolated.

Every arm reserved 384 primitive and 128 query units. The observed arms each
reserved 1,024 inspection units. No timeout, unknown work count, query exhaustion
or inspection exhaustion occurred. No draft reached source screening, candidate
measurement or confirmation. **19 actual native processes / 19 stage reservations,
518.3151 seconds total**, under a maximum allowance of 76.

No model/API call, download, project build or automatic promotion. Money and
electricity costs are unmeasured. `COMPLETE` means the fixed protocol finished;
`ABSTAINED` / `NO_CHECKED_CLOSURE` do not mean the theorem is false.

## What the new observations establish

After removing only the additional `check_id` field, the observe-all arm's
**entire primitive and retrieval traces match the preceding unrestricted
ordering run on all four events**. Baseline also reproduces its 304-step count.
Thus the recorded behavior is not an accidental change in legacy search from
adding metadata, on these tested tasks. This is evidence of observational
non-interference here, not a proof for every possible Lean environment.

The unrestricted arm made 156 discharge attempts: 126 on propositions and 30
on data goals. All 30 data attempts succeeded locally, while only four
propositional attempts did. Of the **17 successful later-goal discharges** that
looked potentially helpful in the previous trace, **16 were data and only one
was a proposition**. A successful `assumption` can select a local list, store,
expression or identifier; it is not necessarily discharging a proof obligation.

Proposition-only mode inspected 310 goals (175 proposition, 135 data) and
skipped all 135 data attempts. There were no unknown-sort or classifier-error
observations in this corpus run; both outcomes have separate control tests.
The skipped raw heads were:

| Raw head | Skip events |
| --- | ---: |
| `List` | 54 |
| `Imperative.PureExpr.Expr` | 38 |
| `Imperative.SemanticStore` | 28 |
| `Imperative.PureExpr.Ident` | 15 |

These are repeated inspection events, not unique goals. The filtered arm made
18 successful propositional discharge attempts, including ten on later goals.
Those speculative branch successes still did not form any complete accepted
proof path. They are not independent proofs, learned rewards or Arena wins.

## Per-event limits and remaining bottleneck

| Event | Baseline steps | Observe-all steps | Filtered steps | Filtered inspections / skips | Filtered depth cutoffs |
| --- | ---: | ---: | ---: | ---: | ---: |
| 13 | 56 | 96 | 96 | 107 / 50 | 0 |
| 14 | 96 | 96 | 96 | 110 / 59 | 1 |
| 17 | 96 | 96 | 96 | 78 / 24 | 9 |
| 2 | 56 | 86 | 61 | 15 / 2 | 0 |

All the primitive savings versus observe-all occurred on event 2. Events 13,
14 and 17 still hit the 96-step limit. Event 17 now reaches both
`UpdateStateNotDefMonotone'` and `UpdateStatesNotDefMonotone'` again (four and
three successful applications, respectively), whereas observe-all did not
reach them before its step cap. It still repeatedly expands the alternating
`updatedStatesInit` / `InitStatesNotDefined` branch before trying those alternatives.

Selected event-17 trace (attempted branches, **not a valid replay path**):

```text
1:  apply updatedStateUpdate
3:  apply InitStatesSomeMonotone
4:  assumption
6:  apply updatedStatesInit
10: apply InitStatesNotDefined
13: apply updatedStatesInit
18: apply InitStatesNotDefined
22: apply updatedStatesInit
28: apply InitStatesNotDefined
32: apply UpdateStateNotDefMonotone'
36: apply UpdateStatesNotDefMonotone'
...
61: apply UpdateStateNotDefMonotone'
63: assumption on later goal 1
...
95: apply UpdateStatesNotDefMonotone'; no complete path within allowance
```

The next supported investigation is guarded repeat-state detection or a bounded
alternative-expansion schedule. Repeated raw heads alone do **not** prove the
goals are equivalent. A loop check must bind local context and relevant
metavariable/universe constraints, or conservatively restrict itself to fully
determined states. That is deferred, not implemented or evaluated here.

The filter also intentionally removes direct data-hypothesis discharge in this
mode; it is not merely moving that action later. A native unknown-sort control
demonstrates that this can miss a valid proof that unrestricted discharge finds.
A late data fallback would be another separately measured policy. This known
incompleteness and the negative real result do not justify enabling the filter
by default. Proposition-driven unification can still assign witness values.

## Evidence and reproducibility

All JSON files are byte-for-byte runtime outputs. `plan.json` binds the complete
protocol; `inventory.json` records the all-pin export; `*-drafts.json` include
bounded queries, primitive traces, kind checks, skips and null proof paths.
`source-binding.json` confirms the frozen snapshot was unchanged before/after.
This was trusted-local execution, not an OS-sandboxed or distributed run.

- Plan ID: `97293e8565e7a17c9130ee6e61d00410d78aa0f96c05ea6a3ece9c3b6b13aca5`.
- Snapshot: 244 files, 5,048,683 bytes.
- Manifest SHA-256: `592a17b97e7ed4359d65def1959694a962c39ee2c4d6679b75a7fdd191d54cd9`.
- Snapshot content hash: `beedaffce69ab75381d3cb98389f88c67c08590f6d9ff355d78888dcf57ec243`.
- Full run, including large capture and reservation journal:
  `/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/proposition-discharge-20260924-6nMAkZ/run`.
- Capture SHA-256: `72f427f50e2385abfca7b69b365a6ebb7597a2f298c0ca5151147f25d909c614`.

Exact executed command (a rerun requires a **new** output directory and fresh
resource reservations; these paths are machine-local):

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  TMPDIR=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp \
  JEVOPS_CAS_DIR=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/proposition-discharge-20260924-6nMAkZ/cas \
  python -I -B /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/proposition-discharge-20260924-6nMAkZ/snapshot/papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py \
  --execute --comparison proposition-discharge --cap 1 --max-processes 76 \
  --nominees /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/proposition-discharge-20260924-6nMAkZ/snapshot/inputs/nominees.json \
  --projects /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/proposition-discharge-20260924-6nMAkZ/snapshot/inputs/projects.json \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
  --snapshot-manifest-sha256 592a17b97e7ed4359d65def1959694a962c39ee2c4d6679b75a7fdd191d54cd9 \
  --output /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/proposition-discharge-20260924-6nMAkZ/run
```

Execution held the exclusive build lock and repeatedly validated the existing
50-GB capped volume. Runtime code remained equal to the frozen tested snapshot
at handoff; documentation was subsequently extended with results.
