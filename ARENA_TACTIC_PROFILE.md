# Bounded tactic heartbeat diagnostics

`ArenaLocalRuntime.profile(pin, source=..., threshold_raw=100)` instruments the
unchanged theorem using Lean's built-in trace profiler. It reuses the existing
project/prefix binding, guarded dependencies, single-process ownership, explicit
invocation budget, bounded pipes, timeout and optional Docker policy. No model,
downloads, build, cache, generated tactic or ambient hook is introduced.

The built-in `trace.profiler.useHeartbeats` option selects raw allocation
heartbeat counters. It is enabled only on the theorem branch, never on prefix
construction. Ordinary capture/replay and the whole-proof Arena checker keep
their original options. The implementation has been exercised on installed
Lean 4.26.0; other version compatibility requires explicit native tests.

## Interpretation and trust boundary

The bounded projection exports `Elab.step` traces tagged
`Lean.Parser.Tactic.*`, with parent IDs, integer start/stop counters, inclusive
cost and bounded pretty-printed hints. It walks at most the requested node
budget, 256 levels and the requested event budget. Overflow fails the operation;
it never silently reports a partial inventory as complete. Missing tactic
traces also fail closed. These bounds cover extraction; Lean's internal trace
construction is subject to the existing heartbeat/wall/output restrictions,
not an added independent memory sandbox.

Python validates the source/context-bound envelope, exact fields and types,
safe integer counters, acyclic preorder ancestry, parent containment and
nonoverlapping ordered siblings. It computes:

- `inclusive_raw`: the recorded interval, including nested work.
- `exclusive_recorded_raw`: inclusive cost minus direct **recorded tactic**
  child intervals. Non-tactic and below-threshold work remain in this number.
- `covered_raw`: sum of roots only, never a sum of parents and children.
- `unattributed_raw`: instrumented command counter minus root coverage.

The exclusive sum equals root coverage. Instrumentation adds work and may
change elaboration cost. These counters must not replace ordinary Arena
measurements, infer an optimization saving or be transferred to uninstrumented
execution as percentages. Hints may be truncated and are **not exact source
offsets, dependency evidence or replay anchors**. Macro expansions and tactic
wrappers can nest; inspect the hierarchy before assigning regions.

Results always keep `proof_admitted=false`, `whole_source_checked=false` and
`score_eligible=false`. A successful profile is `OBSERVED`, not `VERIFIED`.
Injected runner results are `FIXTURE_ONLY`. Integer process units are reserved
before invocation; failures are not refunded, automatically retried or recorded
as counterexamples. Source, implementation or dependencies changing requires
a new context. This is trusted-local diagnostics, not an adversarial security
or independently authenticated measurement claim.

## Frozen single-pin pilot

Plan only, no native calls:

```bash
PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
python -m jevops.arena_profile \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent papers/completion/lean_refactor_arena/evidence/subset-triple-strata-2026-09-25/incumbent.json
```

`arena_profile` is a small diagnostic CLI over the existing runtime, not a new
verifier or search controller. Its fixed schedule contains:

1. Four fresh, **uninstrumented** controls: the 169-token incumbent against the
   original, in both branch orders, twice. Target/type/axiom checks must pass.
2. Six **instrumented** profiles: original/incumbent, incumbent/original,
   original/incumbent, each in its own process. Threshold 100 raw units, 20,000
   traversal nodes, 256 exported events.

Exactly ten process units must be reserved. One non-success stops the run,
retaining partial evidence, without retries or reassigning allowance. Status
`PROFILED` means all diagnostics completed, not that a refactor improved.
The CLI deliberately accepts exactly one declared pin; it does not silently
drop compatibility checks from multi-pin tasks.

`--threshold-raw` may explicitly choose a coarser resolution (0–1,000,000),
frozen into a new plan before execution; the default is still 100. Event/node
caps are unchanged. The first Strata profile exceeded 256 events at threshold
100 and was correctly reported incomplete, with no partial hotspot claim.
Changing the threshold requires a new run and fresh controls, never an
in-place retry or silent truncation of that failed run.

Execution requires `--execute --max-processes 10`, `--snapshot-manifest-sha256`,
`--preparation-root`, `--projects`, `--elan-home`, and a new `--output` directory.
As in `arena_leaf_pilot`, inputs must live inside the read-only source snapshot;
output/temp storage must stay in the capped preparation volume, with the
existing kernel-held lock and 100 MB reserve. All caches are retained.

## Tests and deferred work

Core tests are offline in `tests/test_arena_profile.py`; the single native
control requires `JEVOPS_ARENA_NATIVE_TESTS=1` and an installed pinned toolchain.
It never downloads a toolchain. Existing capture/replay tests cover unchanged
behavior. Profiling cannot nominate edits yet; mapping observations to exact
source spans, profile-guided candidate generation, fresh score confirmation,
multi-pin diagnostic scheduling and stronger execution isolation are separate
work. No benefit is claimed until an uninstrumented refactoring trial succeeds.

The [coarse Strata run](papers/completion/lean_refactor_arena/evidence/tactic-profile-coarse-strata-2026-09-25/README.md)
completed four uninstrumented controls and six native profiles. The unchanged
incumbent's shared simplification prefix accounted for 56.39% of instrumented
command cost in all three repeats; the `ite` case accounted for 4.94%.
This identifies an optimization hypothesis, not an achieved score improvement.
