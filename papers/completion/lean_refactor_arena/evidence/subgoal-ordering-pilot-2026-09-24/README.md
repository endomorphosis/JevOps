# Reversible sibling-ordering pilot: no Arena improvement

Historical exploratory evidence, **not an admission cache, official score or
promoted refactor**. See [implementation and tested commands](../../../../../ARENA_SUBGOAL_ORDERING.md).

## Fixed protocol and result

Public warmup `Core.InitsUpdatesComm`, original source 224 Arena tokens. All
original-proof controls verified on Lean 4.29.1, 4.27.0 and 4.26.0. Both arms
share a fresh 37-event capture and an eight-lemma all-pin inventory. Nominees
are reference-informed; this is not held-out evaluation or model training.

Both use matching-head span selection, typed root retrieval, dynamic subgoal
retrieval, top-k four, depth eight, 96 primitive attempts and 32 queries per
invocation. Each reserves four discovery processes and one shorter draft slot.
The only configuration difference is `discharge_window=8` in the second arm.
Both attempt events **13, 14, 17, 2**, in that order.

| Arm | Primitive attempts | `assumption` | `apply` | Queries | Shorter drafts | Discovery seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 304 | 52 | 172 | 48 | 0 | 95.7008 |
| Sibling discharge | 374 | 156 | 151 | 42 | 0 | 100.1375 |

Outcome: **zero shorter drafts from either arm**. Discharge used 70 more
primitive operations (+23.0%) for the same outcome. This is a regression in
counted work, not a demonstrated refactoring improvement. A primitive unit is
not a constant-time unit, and these single, serial discovery timings do not
establish a statistically meaningful latency difference.

Both arms reserved 384 primitive units and 128 query units. All work counts were
observed; no timeouts or unknown search counts occurred. The baseline exactly
reproduced the preceding trial's depth-eight counts (304 steps, 48 queries).
No candidate reached all-pin screening, measurement or confirmation. No model,
API, download, project build or automatic promotion was used. Money/electricity
costs were not measured. The **15 native processes / 15 stage reservations**
finished in **375.3106 seconds**, under the full protocol ceiling of 57.
`COMPLETE` means the fixed experiment finished, not that it found an improvement.
`ABSTAINED` and `NO_CHECKED_CLOSURE` do not mean the target is false.

## Where the extra work went

| Event | Baseline steps / queries | Discharge steps / queries | Later-goal attempts | Later-goal successful attempts |
| --- | ---: | ---: | ---: | ---: |
| 13 | 56 / 7 | 96 / 8 | 38 | 3 |
| 14 | 96 / 14 | 96 / 10 | 28 | 6 |
| 17 | 96 / 20 | 96 / 14 | 15 | 6 |
| 2 | 56 / 7 | 86 / 10 | 9 | 2 |

The 90 later-goal probes include 17 successful local discharges. These are
speculative, potentially repeated operations on different/backtracked branches,
**not 17 independent proofs or benchmark wins**. The complete paths are all
null. Events 13, 14 and 17 hit the 96-step limit in the new mode. There were zero
depth cutoffs and no query-budget exhaustion; the finite step allowance stopped
those runs before deeper exploration.

For event 17, the new trace begins (zero-based trace indices):

```text
1:  apply Core.updatedStateUpdate       applied, goal 0
3:  assumption                         applied, goal 1
5:  apply Core.InitStatesSomeMonotone   applied, goal 0
6:  assumption                         applied, goal 0
8:  assumption                         applied, goal 1
9:  assumption                         applied, goal 0
11: apply Core.updatedStatesInit        failed,  goal 0
...
47: apply Core.updatedStatesInit        applied on another branch
51: apply Core.InitStatesNotDefined     applied
57: apply Core.InitStatesNodup          applied
...
95: step allowance exhausted without all siblings closing
```

This is an attempted-branch excerpt, **not a replayed proof script**. The mode
does discharge siblings and backtrack; it is not silently behaving like the
old first-goal scheduler. But it also explores goals with raw heads `List`,
`Imperative.SemanticStore` and `Option`, not only propositions. On event 17 it
does not reach either nondefinition-monotonicity lemma before the step cap,
unlike the baseline. Retrieving a useful lemma is still not enough to get the
right assignments and branch within the budget.

The trace does not record every discharge goal's full type or the chosen local
hypothesis, so it cannot attribute every failed branch to a particular wrong
witness. A supported next diagnostic is bounded recording of proposition/data
goal kinds and shared metavariable constraints, then a separately matched
**proposition-only discharge** variant. This is deferred, not a claimed result.
Enumerating alternate matching hypotheses or exact-state loop handling would
also require explicit budgets and separate tests. The present option remains
disabled by default; these results do not justify enabling it globally.

## Evidence and reproduction

JSON files here are byte-for-byte runtime outputs. `plan.json` binds the
protocol; `inventory.json` records the all-pin inventory; the two `*-drafts.json`
files contain full bounded query/action traces, empty drafts and null paths.
`source-binding.json` confirms identical snapshot bytes before/after execution.
This is trusted-local native execution, **not an OS-sandboxed or distributed run**.

- Plan ID: `07eb3dc78e1ba725075ab4090b7612882b40f50063caa4a516744f55a407b97a`.
- Snapshot: 241 files, 4,984,875 bytes.
- Snapshot manifest SHA-256:
  `07a0f66a51184c755fabf51a37beb3853fd8a4a963055c40552fb1fbf5a124d0`.
- Snapshot content hash:
  `3ccb63d168068d99b2d912e9fed31352c0a37bb084fd4839e1cc4f70ceae7a9d`.
- Full run (including the large capture and reservation journal):
  `/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/subgoal-ordering-20260924-4nvkkH/run`.
- Capture SHA-256:
  `ad7e2dfa8e00049da99e68ad18d5466a3c552baaa004d2fd06f2d5fde58160a7`.

Exact executed command (paths are machine-local; a rerun must use a **new**
output directory and a fresh, budgeted protocol invocation):

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  TMPDIR=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp \
  JEVOPS_CAS_DIR=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/subgoal-ordering-20260924-4nvkkH/cas \
  python -I -B /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/subgoal-ordering-20260924-4nvkkH/snapshot/papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py \
  --execute --comparison subgoal-ordering --cap 1 --max-processes 57 \
  --nominees /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/subgoal-ordering-20260924-4nvkkH/snapshot/inputs/nominees.json \
  --projects /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/subgoal-ordering-20260924-4nvkkH/snapshot/inputs/projects.json \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
  --snapshot-manifest-sha256 07a0f66a51184c755fabf51a37beb3853fd8a4a963055c40552fb1fbf5a124d0 \
  --output /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/subgoal-ordering-20260924-4nvkkH/run
```

The exclusive-build lock covered execution and the 50-GB capped volume was
validated throughout. Runtime source files still matched the frozen snapshot
at handoff. Documentation was subsequently extended with the observed results.
