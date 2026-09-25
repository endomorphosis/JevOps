# Scoped subgoal-retrieval pilot

Historical exploratory evidence, **not an admission cache or demonstrated Arena
improvement**. See the [implemented boundary and tests](../../../../../ARENA_SUBGOAL_RETRIEVAL.md).

## Fixed comparison and outcome

Public warmup `Core.InitsUpdatesComm`, original source 224 Arena tokens; eight
reference-informed nominees, not held-out evaluation. All original-proof
controls verified on Lean 4.29.1, 4.27.0 and 4.26.0. The three arms share one
fresh capture, one all-pin typed inventory, matching-head span selection,
initial top-k four, four discovery process slots, one final draft slot and
96 primitive attempts per search. No rewrite action was enabled.

| Arm | Max depth | Observed primitives | Of which `apply` | Queries | Shorter drafts | Discovery seconds |
| --- | --- | --- | --- | --- | --- | --- |
| Fixed shortlist | 4 | 159 | 92 | 0 | 0 | 97.2719 |
| Subgoal retrieval | 4 | 201 | 114 | 27 | 0 | 100.8752 |
| Subgoal retrieval, deeper | 8 | 304 | 172 | 48 | 0 | 89.2610 |

Each arm reserved 384 primitive units; each dynamic arm separately reserved
128 query units. All internal counts were observed (no unknown processes).
Primitive/process **ceilings**, not actual work or query overhead, were matched.
The apparent wall-time differences from this single serial run are not evidence
of faster search; imports/setup/cache effects are not separated by these times.

**19 native processes, 19 stage reservations, 503.1259 seconds total** versus a
maximum allowance of 76. Zero candidate screens, zero candidate measurement,
zero confirmation or promotion. No APIs, models, downloads or project builds.
Actual monetary/electricity costs remain unmeasured. `COMPLETE` means the fixed
protocol finished; `ABSTAINED` means no shorter checked draft, not a false target.

## What changed and what still failed

All arms attempted spans **13, 14, 17, 2**. The fixed arm reproduced the previous
trial's primitive counts exactly: 14, 21, 96, 28. The new mode did not quietly
change root selection or nominees to make the comparison easier.

On event 17 the root shortlist lacks `InitStatesNotDefined`,
`UpdateStateNotDefMonotone'` and `UpdateStatesNotDefMonotone'`. The new retrieval
trace includes all three, and native `apply` successfully applies them. Thus the
specific *premise availability* failure identified in the prior run is fixed.
Those successful primitive actions are only **partial** proof construction;
they do not establish the target.

The depth-4 arm makes 15 queries and reaches 12 depth cutoffs on event 17. The
depth-8 arm makes 20 queries and reaches 16 cutoffs there. Both hit the 96-step
cap; neither exhausts its 32-query allowance. The deeper trace begins:

```text
updatedStateUpdate
  InitStatesSomeMonotone
    assumption
    updatedStatesInit
      assumption
      InitStatesNotDefined
        updatedStatesInit
          assumption
          InitStatesNotDefined
            ...
```

This is an excerpt of attempted branches, **not an accepted proof path**. The
search repeatedly visits `Core.InitStates` and `Imperative.isNotDefined` heads,
then backtracks through alternatives. Repeated heads alone do not establish
identical goals, so this report does not claim a sound cycle detector exists.

The deeper trace also shows a later branch closing an `InitStates` premise by
assumption before failing its sibling `UpdateState` obligation. That motivates
a separately budgeted experiment solving constraining, locally supported
premises earlier, instead of committing first to a generative premise chain.
It does not establish that reordering alone will solve this benchmark.

Events 13 and 14 now retrieve `InitStatesSomeMonotone` for generated equality
goals (it was absent from their root shortlists). Repeated applications still
do not close those goals; deeper search increases their primitive work from
28/49 to 56/96. Event 13's store-expression mismatch remains a candidate for a
separate, explicit rewrite experiment—not permission to identify the stores
heuristically. The fallback root event 2 also remains incomplete.

Next justified experiment: native, replayable, budgeted premise-ordering and
subgoal discharge, with fixed retrieval and explicit backtracking. Exact-state
cycle handling and guarded rewriting are separate deferred changes. This run
does not demonstrate how those unimplemented methods would perform.

## Evidence identity and reproduction

The JSON files are byte-for-byte original runtime outputs. `plan.json` binds the
protocol, `inventory.json` the all-pin export, and the three `*-drafts.json`
files the selected spans, queries, actions, cutoffs and lack of complete paths.
`context.json` and three controls record the real verification context.

- Plan ID: `5596f1345fcbc098a2b1df3a6d555e8e1e4b56d4d90123e71daf4df79026adad`.
- Snapshot: 242 files, 4,994,778 bytes, unchanged before and after the run.
- Manifest SHA-256:
  `9de896778e107601be7ae4295a535cfd3d9cdcd743a5b51add239be708edd0d5`.
- Source bundle:
  `/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/subgoal-retrieval-20260924-pIFJe9/snapshot`.
- Full run, large capture and reservation journal: sibling `run` directory.
- The large `capture.json` is retained there rather than duplicated here;
  SHA-256: `fc28057e9e9f31c208df81cf62b2248b392c750f7cb170fbb8dd0d4297df9351`.

Documentation was updated with test/results after snapshot creation. The
search, planner, adapter, tests and pilot implementation used in this run were
unchanged. These hashes bind bytes; they are not proof or producer attestation.

Executed command, using equivalent path variables for readability:

```bash
trial_root=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/subgoal-retrieval-20260924-pIFJe9
prep_root=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  TMPDIR="$prep_root/work/tmp" JEVOPS_CAS_DIR="$trial_root/cas" \
  python -I -B "$trial_root/snapshot/papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py" \
  --execute --comparison subgoal-retrieval --cap 1 --max-processes 76 \
  --nominees "$trial_root/snapshot/inputs/nominees.json" \
  --projects "$trial_root/snapshot/inputs/projects.json" \
  --preparation-root "$prep_root" --elan-home "$prep_root/work/elan" \
  --snapshot-manifest-sha256 9de896778e107601be7ae4295a535cfd3d9cdcd743a5b51add239be708edd0d5 \
  --output "$trial_root/run"
```

Choose a fresh output directory for a repeat: overwriting existing outputs is
intentionally refused. Prepared projects and the exclusive 50 GB volume boundary
remain prerequisites; this command does not install or build dependencies.
