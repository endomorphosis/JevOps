# Frozen source copies for native Arena trials

The previous Core selection run verified all 48 observations but correctly
withheld its recommendation after `arena_pareto.py` changed in the shared
workspace. Do not remove that integrity check or relabel that run. Use an
independent source copy for the next experiment.

`jevops/arena_snapshot.py` is a stdlib-only utility for capturing the actual
working-tree files, including uncommitted and untracked implementation changes.
It does not use `git archive HEAD`, discard changes, reset the worktree, build
Lean projects, call models or verify a theorem.

## Snapshot boundary

- Explicitly include the Python package and Lean driver, test files/fixtures,
  configuration, frozen corpus and candidate inputs required by the experiment.
- Copy an external prepared-project manifest under `inputs/`. Its paths still
  refer to the original prepared projects; dependencies are **not** copied.
- Capture the selected file inventory and bytes twice, refusing observed changes
  during capture. This is not an atomic multi-file filesystem transaction.
- Record each file's SHA-256 and size, a hash of the file manifest, Python
  executable/version, and input provenance. Reject symlinks, overlapping inputs,
  unsafe paths, more than 4096 files or more than 64 MiB.
- Make the copy's files and directories read-only. Keep the returned manifest
  SHA-256 outside the snapshot, and verify against that same value before and
  after execution. Added, missing, changed or writable files invalidate the copy.

Read-only permissions isolate ordinary edits in the original workspace. They
are **not an OS sandbox**: a same-user process can change permissions, and hashes
are not signatures. The Python installation and external packages are not
frozen by this tool. The native verifier's environment, toolchain and transitive
artifact checks remain mandatory. Snapshot verification never produces proof
authority or fresh timing evidence; its receipts have `proof_verified: false`.

## Execution

Create a new task directory outside the worktree, for example with `mktemp -d`,
and choose a new child directory for the source copy. The utility is executable
as a file so creating the snapshot does not import the mutable JevOps package:

```bash
python -I -B jevops/arena_snapshot.py create \
  --repo /path/to/JevOps --output-dir /owned/new-run/source \
  --include jevops --include tests --include pyproject.toml \
  --include pytest.ini --include conftest.py --include README.md \
  --include papers/completion/lean_refactor_arena/data \
  --include papers/completion/lean_refactor_arena/evidence \
  --include papers/completion/lean_refactor_arena/space \
  --include papers/completion/lean_refactor_arena/harness \
  --input inputs/projects.json=/prepared/projects.json

# Retain the exact manifest_sha256 returned by create, not a freshly computed
# hash of a potentially modified manifest at verification time.
python -I -B /owned/new-run/source/jevops/arena_snapshot.py verify \
  --root /owned/new-run/source --manifest-sha256 CAPTURED_SHA256
```

Launch Python with `-I -B`, explicitly prepend the copied root to `sys.path`,
and run the copied module. `-I` ignores `PYTHONPATH` and the usual current-directory
import injection; `-B` avoids new bytecode files in the source copy. Confirm the
resolved `jevops.__file__` belongs to the copy. Put all output outside the copy.

For pytest, disable test seals and the cache provider, and give any temporary
files a separate writable directory. A green cached test or a reused timing
receipt is not a fresh experiment.

For the Arena rerun, use the [strict dual selector](ARENA_PARETO_SELECTION.md),
the copied corpus/draft/project manifest, all three required pins, both orders,
two screening and two confirmation repetitions, 48 reserved requests and the
existing prepared workspace's nonblocking `single-build.lock`. Declare the
heartbeat noise-floor policy before execution. If the lock is busy, no native
run has started; do not bypass the lock or duplicate another live job.

After completion, verify the snapshot again against the original manifest hash.
Audit that the stored protocol matches the run's plan, both phases retain every
scheduled observation, contexts match across phases, implementation hashes are
unchanged, and the native selector's recommendation gates passed. Preserve any
failed run rather than changing its status. The generated `report.json` and
`summary.md` remain local observations, not an organizer score, training result,
or automatic production promotion.

## Compact post-run consistency audit

Generate an audit from the stored protocol and report, writing the full details
to files instead of reproducing the receipts in a model response:

```bash
python -m jevops.arena_report_audit \
  --protocol /owned/run/protocol.json --report /owned/run/report.json \
  --output-dir /owned/new-audit
```

The output directory must be new. `audit.json` records each consistency check;
`summary.md` contains sample counts, statuses, token costs and heartbeat ranges.
Checks include the precommitted protocol, reconstructed schedules, unique sample
identities, receipt/request/context bindings, recomputed cost analysis, fixed
confirmation winner, context equality, selection commitment, and process/budget
accounting. Missing, malformed or inconsistent evidence exits nonzero. A failed
or incomplete selector result is never relabeled as a confirmed improvement.

This is **historical-report inspection**, not a saved-report admission API.
Coherently fabricated JSON can pass consistency checks. The audit reports
`proof_verified: false` and zero fresh native processes even for a consistent
report. It does not revalidate external dependencies, authenticate receipts,
change an incumbent, start training or grant proof authority. Recomputed analysis
uses the locally installed selector; its source hash and whether it matches the
recorded selector are included. Snapshot checks and fresh native confirmation
remain separate requirements. Keep the original reports, including failures.

## Validation, 2026-09-23

The new snapshot utility captured 343 files and passed 24 tests. The targeted
suite executed from that copy had 365 passes and 82 opt-in native skips; its
externally retained manifest hash still matched after testing. After adding the
report generator and integrating concurrent tests, the workspace's targeted
suite had **421 passes and 82 opt-in native skips**, with test seals disabled.

A matching native trial already held the prepared-project lock, so no duplicate
trial was launched. It used a separately prepared 103-file package copy, not the
343-file test snapshot. That package matched its manifest when inspected during
the run and after completion. The selector reported unchanged implementation
and **48/48 VERIFIED** observations (24 screening, 24 fresh confirmation).

The [stored native report](papers/completion/lean_refactor_arena/evidence/native-strict-dual-core-2026-09-23.json)
confirms the known `Core.InitsUpdatesComm` repair under `strict-dual-v1`:
224 to 216 proof tokens, with approximately 37.89%, 41.32% and 42.40% lower
mean raw heartbeats on the three respective pinned versions, in both orders.
These are local heartbeat observations, not wall-time gains or a new high score.
No proof was promoted and no autoencoder was trained.

The [generated consistency audit](papers/completion/lean_refactor_arena/evidence/native-strict-dual-core-audit-2026-09-23/summary.md)
has no failed checks. Its JSON records that the current audit helper's selector
file differs from the frozen runtime: concurrent CLI repair-proposal additions
occurred outside that copy. Recomputed schedules and cost analyses still match;
this does not replace the runtime's own integrity checks or establish fresh proof
authority. The previous mutable-worktree run remains `INCOMPLETE`.
