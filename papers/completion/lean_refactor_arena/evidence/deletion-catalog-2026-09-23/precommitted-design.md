# Deterministic deletion-catalog feasibility screen

Follow-up to the [rejection-feedback pilot](REFACTOR_DELETION_FEEDBACK_EXPERIMENT.md).
Before further model selection experiments, check whether its action space
contains a valid shorter proof. This is a fixed catalog screen, not iterative
minimization, an official Arena score, or a balanced heartbeat comparison.

## Precommitted protocol

Task: `Core.InitsUpdatesComm`, same source and 64 one-span deletions as the
prompt pilots. Catalog content hash (SHA-256):
`52677802aa9a72d367b5a883b0b552a21d71b1d948af13ef7e1026e12f052219`.
Generate each edit from the original source with the existing proof slicer;
preserve every untouched byte. Do not compose edits, prune using old failures,
change the statement, or reorder executable tactics. Deduplicate exact sources
but preserve the mapping from every action ID. The slicer is a layout heuristic,
not Lean dependency analysis or an exhaustive space of all possible deletions.

Native order: Lean 4.26.0, 4.27.0, 4.29.1, each with its exact corpus commit.
One fresh reference control followed by remaining candidates on each version,
reference-first driver order, 90-second request timeout. Stop a candidate after
its first non-VERIFIED result; later checks are explicitly not run. A failed
control stops further execution. Reserve at most **195 requests**, including
controls and failures; no retries, model calls, downloads or dependency builds.

Use the existing `NativeLeanVerifier` and `ArenaEvaluator` with cache disabled:
target identity, preserved type, original declaration absence, axiom policy,
dependency fingerprints, receipt binding and a fresh process are required.
Passing tests or lexical intake cannot supply proof evidence. A REJECTED edit
is infeasible under the all-version requirement; a timeout/infrastructure error
is inconclusive, never proof of infeasibility. All-pin verification is still
only validity screening: heartbeat claims require a separate fresh balanced
`arena_trial` confirmation, not selection on these single observations.

Execute from a read-only source snapshot with captured project manifest, under
the existing exclusive preparation lock and 50 GB capped volume, one native
process at a time. These are trusted-local private scratch checks, **not an OS
sandbox**. Imported Lean projects/metaprograms remain trusted. Host Python and
Lean dependencies are not copied into the source snapshot; native context
checks still bind them. Snapshot hashes establish identity, not correctness.

Plan, per-request reservations, contexts and checked result rows are written
exclusively and fsynced. Existing output directories are refused even after
interruption, so rerunning cannot silently double-charge/reverify a slot.
Incomplete archives retain reservations, not fabricated outcomes. An explicit
new run/directory is necessary for a retry. The final report classifies every
action and keeps transient failures separate. No training or promotion.

## Commands

Review the plan without executing Lean or calling a model:

```sh
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
python papers/completion/lean_refactor_arena/tools/run_deletion_catalog_sweep.py --max-requests 195
```

After capturing source, corpus, harness, tool and project manifest using
`jevops.arena_snapshot`, execute the copied tool (all variables are explicit
paths/identities for that isolated run):

```sh
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
JEVOPS_CAS_DIR="$SWEEP_BASE/cas" TMPDIR="$PREPARATION/work/tmp" \
python -I -B "$SNAPSHOT/papers/completion/lean_refactor_arena/tools/run_deletion_catalog_sweep.py" \
  --execute --max-requests 195 --preparation-root "$PREPARATION" \
  --output "$SWEEP_BASE/run" --projects "$SNAPSHOT/inputs/projects.json" \
  --elan-home "$PREPARATION/work/elan" --snapshot-manifest-sha256 "$SNAPSHOT_SHA256" \
  --reviewed-catalog-sha256 52677802aa9a72d367b5a883b0b552a21d71b1d948af13ef7e1026e12f052219
```

Without `--execute` only a plan is emitted; budget defaults to zero.
Core regression tests inject explicitly labelled offline receipts and never
execute Lean or a model. Live results will be archived separately from fixtures.
