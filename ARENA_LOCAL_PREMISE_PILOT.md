# Project-context local premise pilot

This increment connects the existing scoped premise index to real Arena
InfoTree closing spans. It does not import `ipfs_datasets_py`, run an ATP,
train a model, promote a checkpoint or change the production outer loop.
See [the adapter contract](ARENA_PROVIDERS.md#arena-project-context-and-controlled-comparison).

This note retains the original pilot's failures. The subsequent
[local-context repair](ARENA_LOCAL_CONTEXT_REPAIR.md) identifies and fixes the
opaque-have encoding and module-audit issues, and guards against synthetic
branch-header edits. Follow-up measurements are recorded separately; historical
receipts below are not relabelled or overwritten.

## Fixed exploratory protocol

The already-inspected warmup task is `Core.InitsUpdatesComm`, with corpus pins
Lean 4.29.1, 4.27.0 and 4.26.0. Eight explicitly nominated library declarations
come from its reference proof. This is neither a held-out evaluation nor an
unrestricted library search. The native exporter establishes their actual
target-free availability, types and dependencies on every pin; caller metadata
alone cannot establish those facts.

Compare the existing whole-proof premise provider with the local closing-span
provider, both using the same inventory, two-draft cap, fresh whole-source
verification and stop-on-first-non-verified-pin rule. Local proposals receive
additional capture/replay work, reported separately. Failed local replays are
not used to prune the whole-source comparison. Only all-pin-valid candidates
qualify for fresh measurements in both execution orders, twice each. There is
no independent confirmation or promotion in this small experiment.

The current plan ID, including the explicit `closing-source-spans/v1`
projection, is
`068b18513e164ae99c89b74bc8680a64978c4aa32cbc14caa332214154bb7904`.
The worst-case reservation is 81 native process units: 9 discovery, 12 screen,
and 60 measurement units. Unused reservations are not measurements. API calls
are disabled; API/electricity costs are unmeasured, not fabricated dollar values.
Execution is sequential, trusted-local (not OS sandboxed), inside the existing
50,000,000,000-byte provisioning boundary. No dependency builds or downloads are performed
by the pilot. Dependency identity validation remains global work and contributes
to wall time; this is not a local-update scalability benchmark.

## Reproduction

Plan only, offline:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py \
  --nominees papers/completion/lean_refactor_arena/evidence/local-premise-core-nominees.json \
  --cap 2 --max-processes 81
```

For native execution, create a new [read-only source snapshot](ARENA_FROZEN_RUNS.md)
including `jevops`, `papers/completion/lean_refactor_arena/harness`, the warmup
JSONL and `tools/run_local_premise_pilot.py`. Capture prepared project bindings
as `inputs/projects.json` and the nominees as `inputs/nominees.json`. The
existing prepared projects/toolchains are required; the script does not provision
them. Use task-specific shell variables pointing to your explicit owned paths:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  TMPDIR="$ARENA_PREP/work/tmp" JEVOPS_CAS_DIR="$ARENA_RUN/cas" \
  python -I -B "$ARENA_SNAPSHOT/papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py" \
  --execute --cap 2 --max-processes 81 \
  --nominees "$ARENA_SNAPSHOT/inputs/nominees.json" \
  --projects "$ARENA_SNAPSHOT/inputs/projects.json" \
  --preparation-root "$ARENA_PREP" --elan-home "$ARENA_PREP/work/elan" \
  --snapshot-manifest-sha256 "$ARENA_SNAPSHOT_SHA256" --output "$ARENA_RUN/run"
```

The new output must be inside the capped preparation volume. Source identity is
verified before/after work, and the preparation lock prevents overlapping work
using this protocol. This is single-process experiment ownership, not a claim
about arbitrary concurrent users or cross-process proof-store transactions.

## Retained initial failure

The initial snapshot manifest was
`e53fa2b467ca3a580813f5d584440004dc0e2e05dfd1ab230c8ee88f07fc844d`.
The first two attempts used plan
`264ea1e0ad87631a04dda5a8152b6bf8d35c5a286a351d56bfb6614175bed3f3`,
before the explicit closing-span projection was added.
All three reference controls passed and all eight nominees survived the native
inventory intersection. Capture then failed with `trace byte budget` before any
draft was screened: seven reservations/launches, 228.2309 seconds. Its status is
`INCOMPLETE`, not zero proof accuracy or zero compression. The report, failed
capture, plan and snapshot verification are retained in
[evidence/local-premise-pilot-2026-09-23](papers/completion/lean_refactor_arena/evidence/local-premise-pilot-2026-09-23).
The complete original run remains at
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/local-premise-pilot-20260923-xKMzSe/run`.

The exporter fix reserves an equal share of the same 16,000,000-byte event
payload budget for each possible event. Oversized observations become wholly
`unsupported`, with IDs/parents/spans retained. No local context is truncated,
no byte limit is raised and no verification gate is relaxed. This sacrifices
observation coverage explicitly; small later observations can still be used.
The exporter hash changes, so earlier captures are historical and cannot be
reused as current captures.

The follow-up uses the same candidate protocol with new snapshot manifest
`707ba55b95843b9cd633b2c9a605c0f6f966fc13e8de145336db937a27a7317f`, stored at
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/local-premise-pilot-20260923-GUWVeU`.
It is a post-fix exploratory run, not an independent held-out confirmation.
It also stopped before screening, now with `event budget`: more than 256 native
tactic events were present. Its seven process launches and full failure report
are retained as `byte-fix-*.json` in the same evidence directory.

The next snapshot is
`0cc60be7a7eacb272a21b9687232b8f692941e928210c55939b1f74dc337e6f0`, at
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/local-premise-pilot-20260924-TYKeUj`.
Its explicit projection visits the bounded InfoTree but retains only the first
single-goal closing event per distinct nonempty source span. This intentionally
excludes open transitions and other internal contexts sharing that span.
The same selected native references supply replay, and the receipt must match
the saved event exactly. Global traversal/event limits, complete state validation,
kernel/axiom checking and all-pin whole-source verification remain in force.
This changes observation coverage, not the task, nominee set or draft/screen cap.
That attempt captured 37 source spans but failed structural validation with
`unbound variable in local context` (34 before-states; all 37 after-states passed
the state validator). It launched seven processes in 224.1123 seconds and
screened no drafts. The report and raw-capture digest/path are retained as
`projection-*.json`. These are observation limitations, not counterexamples to
the original theorem.

The native encoder now applies the existing wire validator's scope restriction
before declaring a state captured. Roots mentioning undeclared free variables
or loose bound variables make the whole event unsupported; no locals,
assignments or dependencies are filled in or removed. Synthetic native tests
cover both unbound goal types and unbound assignments. This makes the adapter
abstain per event without relaxing the admission boundary.

The final source snapshot for this increment is
`11d9103a6fd1f2f4f815907716e6efbcb14ecf5b563b8a465cd744ecb4c0fd2b`, at
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/local-premise-pilot-20260924-vbLY69`.
It uses the current closing-span plan, fresh controls and a fresh native
inventory, without reusing the earlier failures as verification receipts.

## Observed final result (2026-09-24)

The [final report](papers/completion/lean_refactor_arena/evidence/local-premise-pilot-2026-09-23/final-report.json)
has status `COMPLETE`: the fixed screening protocol finished, **not** that an
improved proof was found. All three original-reference controls passed; all
eight library nominees were available in the all-pin inventory.

| Proposal family | Drafts | Rejected at first pin (4.29.1) | All-pin-valid |
| --- | ---: | ---: | ---: |
| Whole-proof premise retrieval | 2 | 2 | 0 |
| Local closing-span premise retrieval | 2 | 2 | 0 |

The final capture contained **37 distinct closing spans: 3 complete observations
and 34 unsupported observations**. All 34 abstentions reported the local-scope
restriction. The three supported observations cover the outer proof/root syntax,
not successful capture of its inner subgoals. Both emitted local candidates came
from event 2 (the body-wide tactic sequence), not a small inner rewrite. This is
an important negative coverage result: the pilot does not demonstrate that local
retrieval has improved this theorem's inner proof search.

Both local replays also failed to establish a checked baseline: their native
baseline outcome was `replay uses forbidden axioms`, while the independent
all-pin whole-proof controls passed. The exact source of this audit discrepancy
is **not resolved** by this increment. The baseline was not relabelled as valid,
the axiom policy was not weakened, and these replays supply no teacher labels.
Candidate diagnostics separately reported type mismatches. As
predeclared, the failed local replays did not skip whole-source screening; all
four drafts were freshly rejected with `candidate_errors` on the first pin.
The remaining pins were not run for those already-rejected drafts.

The completed run reserved/launched **13 native processes** (3 controls,
3 inventory probes, 1 capture, 2 local replays, 4 screens), with reported wall
time **334.6633 seconds**. Across the four retained pilot attempts there were
**34 native launches**, excluding regression-test processes. No candidate
heartbeat measurement stage ran because there were no all-pin-valid survivors.
No verified token/heartbeat improvement, statistical superiority or official
Arena score was established. No model calls, downloads, dependency builds, training,
promotion or commits were performed by this pilot.

Raw captures, drafts, inventory and replay reports remain in the final run
directory above. The repository evidence directory retains the full final
plan/context/report/source-snapshot checks and compact capture/replay summaries
with raw artifact paths and SHA-256 content hashes. Hashes establish identity,
not proof. Both snapshot checks reported `UNCHANGED`.

The next useful work is to understand the unsupported intermediate local scopes
and reconcile project replay's axiom audit with the whole-proof verifier. Only
then can a meaningful small-span comparison evaluate argument-aware premise
application or bounded tactic search. Simply increasing the draft count here
would mostly spend more checks on unsupported contexts or body-wide guesses.

## Implementation scope

- `jevops/arena_local.py` and `jevops/lean/ArenaLocal.lean`: explicit project
  context, invocation budgets, origin binding, capture and checked local replay.
- `jevops/lean/ProofState.lean`: shared command-state trace/replay functions,
  identical capture/replay event selection, per-event wire bounds and explicit
  scope abstention. Standalone full-trace selection remains the default.
- `jevops/proof_replay.py` and `jevops/arena_providers.py`: thin project-origin
  compatibility checks; project captures cannot silently use ambient replay.
- `tools/run_local_premise_pilot.py` and the fixed nominee JSON: frozen,
  sequential, plan-first whole/local comparison with no automatic promotion.
- `tests/test_arena_local.py`, `tests/test_local_premise_pilot.py` and
  `tests/lean/ProofStateTest.lean`: project boundary, orchestration/budget,
  malformed receipt, byte-limit and unbound-variable regressions. Existing
  proof-state/replay/local-premise tests were also rerun.

The changes are in the current dirty checkout; unrelated work was preserved.

## Regression commands

Offline (native flags unset and older auto-native scoped cases deselected):

```bash
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

Observed after the closing-span changes: **563 passed, 13 skipped, 9 deselected**,
9.85 seconds on the final source.

Explicit native controls, with already-installed toolchains:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  JEVOPS_ARENA_NATIVE_TESTS=1 ELAN_TOOLCHAIN=leanprover/lean4:v4.26.0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_proof_state.py::test_native_universe_context_and_delayed_assignment_rejection \
  tests/test_arena_local.py::test_native_project_prefix_target_offsets_replay_and_whole_proof \
  tests/test_local_premise_replay.py::test_native_local_candidate_replay_and_whole_theorem
```

The targeted five controls passed after the closing-span change. The final
expanded native regression command was:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  JEVOPS_ARENA_NATIVE_TESTS=1 ELAN_TOOLCHAIN=leanprover/lean4:v4.26.0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_proof_state.py tests/test_proof_replay.py \
  tests/test_arena_local.py::test_native_project_prefix_target_offsets_replay_and_whole_proof \
  tests/test_local_premise_replay.py::test_native_local_candidate_replay_and_whole_theorem
```

Observed: **82 passed**, 88.51 seconds. This includes native byte-budget checks,
project namespace/section contexts on Lean 4.26.0 and 4.34.0, and positive/negative
standalone replay controls. The negative control falsely describes `False.elim`
as a proof of `True`; local replay and whole-proof verification reject it.
These are correctness controls, not performance wins.
