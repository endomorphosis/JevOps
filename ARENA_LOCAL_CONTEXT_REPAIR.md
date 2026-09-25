# Local-context and replay-audit repair (2026-09-24)

This fixes two infrastructure failures exposed by the
[first Strata local-premise pilot](ARENA_LOCAL_PREMISE_PILOT.md), without changing
its proof target, nominees, draft cap, process ceiling or acceptance gates. It
does not add an ATP, run a model, train weights or promote refactors.

## Root causes and trust boundary

1. **Opaque have-bindings were treated as definitions.** The old encoder exported
   hidden values even when Lean marked a local declaration `nondep=true`. In the
   captured `Core.InitsUpdatesComm` context, `Hlen1`'s hidden value referenced a
   removed variable, although its type was still valid. Lean explicitly permits
   stale/type-incorrect hidden values for these opaque have-bindings: see the
   installed Lean 4.26.0 source, `src/lean/Lean/LocalContext.lean`, the `LocalDecl`
   documentation and `value?` implementation. They must generally behave as
   typed variables, not transparent definitions.
2. **Local replay inspected only public module theorem views.** The whole-proof
   Arena audit already loads matching private imported bodies for transitive
   inspection. The local audit instead classified the public axiom-shaped views
   as axioms. It therefore rejected a valid baseline that the whole-proof
   verifier accepted. Reusing the existing audit distinguishes those theorem
   views from real axioms; merely expanding the allowed-axiom list would not.

`ProofState.lean` now exports versioned V2 states, retaining the typed opaque
declaration with `nondep=true, value=null`. Transparent lets, types, assignments
and instances keep complete scope checks. Python supports V1 under its original
contract and V2 under the explicit new contract; it does not silently upgrade
old captures. Source/exporter/adapter hashes invalidate stale replay anchors.
Replay explicitly generalizes opaque haves when constructing closed telescopes.

`ArenaLocal.lean` injects the whole-proof module audit through the shared replay
interface. It audits the same **original** environment used for kernel checking,
not an environment substituted by a tactic. Richer imports are audit-only;
private names are not made available to elaboration. The allowed axioms remain
exactly `propext`, `Classical.choice`, and `Quot.sound`. Local replay remains a
conditional proof of the local telescope, never whole-source admission.

## Regression coverage

New cases cover opaque haves after `clear`, rejection of the same stale value
in a transparent let, V1/V2 compatibility, real hidden axioms, private-name
visibility and a malicious environment-replacing candidate. Arena rejects that
candidate's `run_tac` envelope before reserving or launching work; the existing
standalone native test independently checks original-environment auditing as
defense in depth. An initial test incorrectly expected the Arena candidate to
reach Lean; its expectation was corrected, not the envelope restriction.

Commands actually run with test-seal reuse disabled:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  JEVOPS_ARENA_NATIVE_TESTS=1 ELAN_TOOLCHAIN=leanprover/lean4:v4.26.0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_proof_state.py tests/test_proof_replay.py tests/test_arena_local.py

env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  JEVOPS_ARENA_NATIVE_TESTS=1 ELAN_TOOLCHAIN=leanprover/lean4:v4.26.0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_arena_module_audit.py -k 'v4.29.1 or v4.27.0'

env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_arena_local.py tests/test_local_premise_pilot.py \
  tests/test_local_premise_replay.py tests/test_arena_premises.py \
  tests/test_arena_providers.py tests/test_premise_search.py tests/test_arena.py \
  tests/test_arena_trial.py tests/test_arena_pareto.py tests/test_refactor_prompts.py \
  tests/test_refactor_prompt_archives.py tests/test_scoped_proposals.py \
  -k 'not native_generated and not before_context_never_copies and not stale_capture_abstains and not native_admission'
```

Observed after the state/audit repairs: **103 passed** (73.82 seconds);
**16 passed, 21 deselected** (101.04 seconds); **563 passed, 13 skipped,
9 deselected** (9.73 seconds), respectively. After the branch-header guard
below, the first and third commands were rerun: **105 passed** (92.48 seconds)
and **566 passed, 15 skipped, 9 deselected** (9.79 seconds). Test counts include
Python cases, not only native processes.
The module selection uses already-installed Lean 4.27.0 and 4.29.1; no downloads
or dependency builds occurred. This is focused regression coverage, not a claim
that the entire repository suite was run.

## Follow-up found by the real-project run

Snapshot `22b3b69858728f7a2a0d73b3ae6e65e395603d6a937fdb019d32ad195e09c1ed`
captured all **37/37** selected spans, with zero unsupported states (previously
3/37). The fixed pilot completed in 342.3512 seconds, using 13 native processes;
neither proposal family produced an all-pin-valid candidate. Its
[unaltered report](papers/completion/lean_refactor_arena/evidence/local-context-repair-2026-09-24/initial-report.json)
and compact capture/replay summaries are retained.

The newly visible inner contexts exposed a third issue: the provider selected
event 19, `next val heq =>`. Lean records this synthetic `null` InfoTree node
with useful before/after states, but it is not an independently executable
tactic. Both baseline replays therefore failed with `Unexpected tactic`, not
the earlier axiom diagnostic. A valid observation is not necessarily an editable
span or a replayable transition.

`proof_replay.replace_event` now rejects synthetic `null` nodes and bare `=>`
spans. They remain in the diagnostic capture, but existing proposal generation
records `UNSUPPORTED_SPAN` and spends no draft slot on them. The explicit Arena
adapter rejects these edits before reserving a native invocation. Full branch
bodies remain eligible; this guard is not a complete Lean parser. Added fixtures
check `next`, `case`, and bare-arrow headers with a one-draft budget, plus native
controls that reject real InfoTree headers and successfully replay their inner
`exact` tactic. The proposal guard is a new source epoch; old captures/reports
are retained rather than edited or reused as current evidence.

## Frozen rerun and reproduction

The final source snapshot is
`538b40785a1e1b3b942678a7802c2756bdf823d18f0d1f67af141d4f41d442a0`, at
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/local-context-repair-final-20260924-EZ4CQQ/snapshot`.
It uses the unchanged pilot plan
`068b18513e164ae99c89b74bc8680a64978c4aa32cbc14caa332214154bb7904`.
The first launch stopped at the preparation lock, before reserving work or
launching Lean. It was retried only after the other experiment released the
lock; no process was interrupted and the one-at-a-time restriction was preserved.

The exact invocation uses these task-specific paths (for a new reproduction,
make a fresh snapshot/output following the original pilot guide):

```bash
ARENA_PREP=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM
ARENA_RUN="$ARENA_PREP/work/local-context-repair-final-20260924-EZ4CQQ"
ARENA_SNAPSHOT="$ARENA_RUN/snapshot"
ARENA_SNAPSHOT_SHA256=538b40785a1e1b3b942678a7802c2756bdf823d18f0d1f67af141d4f41d442a0
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  TMPDIR="$ARENA_PREP/work/tmp" JEVOPS_CAS_DIR="$ARENA_RUN/cas" \
  python -I -B "$ARENA_SNAPSHOT/papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py" \
  --execute --cap 2 --max-processes 81 \
  --nominees "$ARENA_SNAPSHOT/inputs/nominees.json" \
  --projects "$ARENA_SNAPSHOT/inputs/projects.json" \
  --preparation-root "$ARENA_PREP" --elan-home "$ARENA_PREP/work/elan" \
  --snapshot-manifest-sha256 "$ARENA_SNAPSHOT_SHA256" --output "$ARENA_RUN/run"
```

The separate one-process
[`replay_reference_control.py`](papers/completion/lean_refactor_arena/evidence/local-context-repair-2026-09-24/replay_reference_control.py)
replays the original body-wide event 2 as its baseline, with `skip` as an explicit
non-closing negative candidate. It checks the original axiom failure directly;
neither source shortening nor candidate acceptance is expected. It uses the
same frozen implementation/context, preparation lock and resource boundary:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  TMPDIR="$ARENA_PREP/work/tmp" JEVOPS_CAS_DIR="$ARENA_RUN/cas" \
  python -I -B papers/completion/lean_refactor_arena/evidence/local-context-repair-2026-09-24/replay_reference_control.py \
  --run-root "$ARENA_RUN" --preparation-root "$ARENA_PREP" \
  --snapshot-manifest-sha256 "$ARENA_SNAPSHOT_SHA256"
```

Both commands refuse to replace existing outputs. The extra diagnostic is
accounted separately from the matched whole/local candidate screening budget.

## Final observed results

The [final report](papers/completion/lean_refactor_arena/evidence/local-context-repair-2026-09-24/final-report.json)
has status `COMPLETE`: the fixed comparison finished, not a successful refactor.
All three reference controls passed; all eight nominees survived the all-pin
inventory. Capture retained **37/37 valid observations**, versus **3/37** before
the repair, with zero unsupported snapshots. These include diagnostic-only
headers; this is not a claim that all 37 spans are independently replayable.

The proposer now skips the observed wrapper/header spans (events 1, 18, 19 and
3) and selects event 15, `split at Hdef <;> simp_all`. Both candidate trials use
this **same** inner goal, not two independent successful goals. Its original
baseline reaches `closed_kernel_checked`, with one closed goal and only
`propext`, in both trials. The proposed bare library references fail with type
mismatches; local replay does not convert those failures into teacher labels.
As predeclared, those failures do not prune independent whole-source screening.

| Proposal family | Screened drafts | First-pin rejections | All-pin-valid |
| --- | ---: | ---: | ---: |
| Whole-proof premise retrieval | 2 | 2 | 0 |
| Local closing-span premise retrieval | 2 | 2 | 0 |

All four whole-source rejections are `candidate_errors` on Lean 4.29.1; later
pins are not run for already-rejected candidates. No heartbeat-measurement stage
ran, and no token/heartbeat gain, official score or superior search quality was
established. The final pilot used **13 native processes in 341.9962 seconds**.
The earlier diagnostic pilot used another 13; regression-test launches are not
included in either count.

The [separate original-body control](papers/completion/lean_refactor_arena/evidence/local-context-repair-2026-09-24/reference-replay-summary.json)
also **passed**: event 2's original baseline is now `closed_kernel_checked`,
with precisely the permitted `Quot.sound`, `propext`, and `Classical.choice`.
This is the same body-wide replay path that previously failed its axiom audit.
The explicit negative `skip` candidate correctly leaves one open goal, so
`closing_reproduced=false` is the expected control outcome, not a failed
baseline. It used **one native process in 49.4925 seconds**, separately from
candidate screening. Total diagnostic/pilot launches this increment: **27**,
excluding tests; the locked launch attempted zero.

Before/after source checks all reported `UNCHANGED`. Full raw captures, drafts,
inventory and replay reports remain in the named preparation-volume runs.
The repository archive retains full plans, contexts, screening reports and
source checks, plus generated compact summaries with raw paths and SHA-256
content hashes. They are identities, not proofs. No model calls, downloads,
dependency builds, training, promotion, commits or pushes were performed by
these experiments. Execution remains trusted-local, single-process and not OS
sandboxed. The existing 50 GB preparation boundary remains in force.

## Changed files and remaining limitations

- `jevops/lean/ProofState.lean`, `jevops/proof_state.py`: explicit V2 semantic
  projection, legacy validation and original-environment replay-audit injection.
- `jevops/lean/ArenaLocal.lean`: reuse the existing module-aware Arena audit,
  without changing tactic visibility or the allowed-axiom set.
- `jevops/proof_replay.py`: reject known synthetic branch headers as edits;
  no new verifier, source execution permissions or neural policy.
- `tests/test_proof_state.py`, `tests/lean/ProofStateTest.lean`,
  `tests/test_proof_replay.py`, `tests/test_arena_module_audit.py`,
  `tests/test_local_premise_replay.py`, `tests/test_arena_local.py`: semantic,
  compatibility, adversarial, proposal-budget and native replay regressions.
- README, capture/replay/provider notes, the historical pilot cross-reference
  and this note: actual contracts, commands, results and limitations.
- `evidence/local-context-repair-2026-09-24`: retained generated evidence and the
  bounded reference-control script; earlier negative runs remain unchanged.

These are fixes for reproducible observation, audit and edit-selection faults,
not a general InfoTree replay engine or an improvement in model quality. The
header guard is conservative, not a parser-completeness claim. Other local
states can still exceed bounds or have unsupported/open telescopes. Actual
refactor quality still needs argument-aware premise application or bounded
goal-directed tactic search, followed by fresh all-pin and cost checks. That
search work is deferred; no arbitrary relaxation of proof/axiom admission is
needed to pursue it now.
