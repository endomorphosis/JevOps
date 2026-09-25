# Deterministic deletion-catalog feasibility screen

Follow-up to the [rejection-feedback pilot](REFACTOR_DELETION_FEEDBACK_EXPERIMENT.md).
Before further model selection experiments, check whether its action space
contains a valid shorter proof. This is a fixed catalog screen, not iterative
minimization, an official Arena score, or a balanced heartbeat comparison.

## Observed result — September 23, 2026

**0/64 valid deletions.** All 64 distinct candidate sources were rejected on
Lean 4.26.0. All three reference controls verified. The 128 later candidate/pin
checks were explicitly `NOT_RUN_AFTER_NON_SUCCESS`, not failures or successes.
There were no timeouts, unavailable verifiers or infrastructure errors.

| Measurement | Observed |
| --- | --- |
| Fresh native verification requests/processes | 67 / 67 |
| Reference controls verified | 3 / 3 |
| Candidate edits rejected on first pin | 64 / 64 |
| All-pin verified candidates / inconclusive candidates | 0 / 0 |
| Model requests | 0 |
| Summed request wall time | 783.5221 seconds |
| Sweep wall time including context setup | 829.0873 seconds |

The original proof has 224 tokens. Every catalog candidate is shorter
(27–223 tokens), but **token deletion without a valid proof is not an
improvement**. No balanced performance confirmation, training, promotion or
official scoring occurred; API/electricity cost was not measured.

The most common first diagnostic was `unsolved goals` (25 edits). For example,
ID 54 deletes body line 3 (`have Hk ...`). Its diagnostics include a changed
induction-hypothesis application: `ih Hinit ?_` already returns a conjunction,
so the remaining extra argument is invalid. It also reports `simp_all` making
no progress. This suggests coupled deletion-and-repair proposals, not that a
particular repair has already been proved by this screen. Each repair must
receive fresh whole-proof checks, and any performance claim needs a separate
balanced confirmation.

The catalog is identical to the prompt pilots, but this is a **new verification
context**. Native dependency fingerprints include absolute source-snapshot
paths; the new hashes differ from the preceding pilot. Verifier implementation
identity and options match that pilot. No old receipt supplied a result here.
The source snapshot checks before and after execution both report `UNCHANGED`.

Conclusion: selection-only prompt changes cannot yield an admitted refactor
from these 64 checked sources in this context. Expand the permitted edit
actions (for example, deletion plus dependency/argument repair) before more
selection-only prompt comparisons. This does **not** establish that every
possible deletion fails, that this theorem cannot be shortened, or that
feedback/prompt engineering is generally ineffective. The catalog is capped
and heuristic; it does not enumerate all Lean refactors.

The [machine-readable summary](papers/completion/lean_refactor_arena/evidence/deletion-catalog-2026-09-23/summary.json)
lists every edit, source identity, token count and first diagnostic. Its
[evidence archive](papers/completion/lean_refactor_arena/evidence/deletion-catalog-2026-09-23/)
contains the fixed plan, all 195 result rows, 67 unique request reservations,
fresh receipts, contexts, source-binding checks, snapshot manifest and the
pre-run protocol. A post-run consistency audit recomputed all request/source
identities, matched individual rows to the aggregate report, and checked all
three control axiom reports. This is not a second independent Lean verifier.
The archive manifest binds 272 artifacts (685,690 bytes); hashes are not proofs.
The full 226-file source snapshot remains private at the path below.

## Implementation and tests

- `papers/completion/lean_refactor_arena/tools/run_deletion_catalog_sweep.py`:
  deterministic source-bound proposals and bounded, fail-fast native screening
  through the existing verifier/evaluator. No model framework or new dependency.
- `tests/test_deletion_catalog_sweep.py`: 21 offline cases covering the exact
  prior catalog, byte preservation, zero/boundary budgets, source deduplication,
  per-pin requirements, interrupted/completed replay refusal, receipt/context
  mismatches, process freshness and explicit inconclusive outcomes.
- `README.md`: links this reproducible experiment and its limitations.

Observed targeted suite result: **526 passed, 82 skipped, 1 deselected in
22.13 seconds**. The skips are opt-in native tests; the installed-Lean proof
slicer test was explicitly deselected. This was not the whole repository suite.

```sh
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --test-seal=off \
  tests/test_deletion_catalog_sweep.py tests/test_deletion_feedback_pilot.py \
  tests/test_deletion_id_pilot.py tests/test_deletion_order_pilot.py \
  tests/test_local_edit_proposals.py tests/test_prompt_template_pilot.py \
  tests/test_refactor_prompts.py tests/test_arena_snapshot.py \
  tests/test_leanstral_prompt_lab.py tests/test_leanstral.py \
  tests/test_arena_trial.py tests/test_proof_slicing.py \
  tests/test_arena.py tests/test_arena_lean.py -k 'not real_kernel_checked'
```

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
execute Lean or a model. Live results are archived separately from fixtures.

Values used for the completed native command above (do not reuse its output
directory; a repeat requires an explicit new run):

```sh
PREPARATION=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM
SWEEP_BASE="$PREPARATION/work/deletion-catalog-20260923-wEXRF9"
SNAPSHOT="$SWEEP_BASE/snapshot"
SNAPSHOT_SHA256=636f1549d31ac65ec9ddbd04110e32913d6f6294c0e677afa9e910359cb9d364
```

Plan ID: `f45580980c3d51fa04bd173ec351ce8582be6051c369cc90a0bf76e6a8a86558`.
Snapshot content root:
`8f74d268c02b8db32b6e6cc07941c09061140ad159e8d56490aca58650169c89`.
Neither identity is a proof or a CID.
