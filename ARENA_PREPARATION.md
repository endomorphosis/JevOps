# Bounded, opt-in Arena environment preparation

`jevops.arena_prepare` prepares infrastructure only. A successful build or copied
cache is not proof evidence; run `arena_lean --baseline` afterward. It does not
download by default, invoke a model, change shared Git checkouts, restart the
autoresearch loop, or submit an Arena score. Core tests remain offline.

## Scope-bound native import closures

`jevops.arena_import_closure.ImportClosureDiscovery` can inventory the exact
external module families loaded by the trusted prefix and the verifier's private
axiom audit on **v4.27.0 and v4.29.1**. This is an explicit, bounded host-side
diagnostic, not a candidate execution API. It defaults to zero native calls;
the caller must hold the shared preparation lock and apply the storage guard.
It neither builds nor downloads dependencies. Injected runners are labeled
fixtures, never native evidence.

Discovery rejects prefix errors and a target already present in the checked
environment. Module paths must match the original ordered search roots. Each
selected module retains every present `.olean`, `.olean.server`,
`.olean.private` and `.ir` file. The newer split `.ir.sig` layout is unsupported
and rejected. Compiler-library modules stay in the existing read-only compiler
mount, not in a second copy. These assumptions are pinned to Lean's
[v4.27 artifact loading implementation](https://github.com/leanprover/lean4/blob/v4.27.0/src/Lean/Environment.lean)
and exercised against both supported compilers.

Lean selects the first root containing a **root package**, not the first root
containing the requested submodule. The selected stage therefore preserves
empty top-level package directories, including synthetic blockers for omitted
top-level `.olean` files. This prevents an omitted import from silently falling
through to another root. See the pinned
[import search implementation](https://github.com/leanprover/lean4/blob/v4.27.0/src/Lean/Util/Path.lean).

The library workflow, given a validated original `binding` and `volume`, is:

```python
# Discovery: hold the preparation lock and storage guard around this call.
discovery = ImportClosureDiscovery(binding, max_processes=1, scratch_parent=work)
report = discovery.discover(target)
selection = report["selection"]

# Each public preparation call acquires the same lock itself; do not nest it.
plan = plan_imports(volume, binding.search_paths, selection=selection,
                    max_bytes=128_000_000)
# Only after inspecting a WOULD_FIT plan, with no concurrent source changes:
stage = stage_imports(volume, binding.search_paths, name=unique_name,
                      selection=selection, scope_sha256=report["scope_sha256"],
                      max_bytes=128_000_000)
rebound = binding.with_staged_imports(Path(stage["manifest"]), stage["manifest_sha256"])
```

The new `jevops-arena-selected-import-stage/v1` manifest is bound to the full
original **verification context**, including omitted compiled artifacts, compiler,
source, pins and verifier implementation. `ProjectBinding` rechecks this original
context before admitting or reusing the selected stage. `StagedImports.validate`
alone checks selected file bytes/membership and the expected scope identifier;
it is not a substitute for the binding's whole-context check. Build `.hash` and
editor `.ilean` files are not verification inputs. All source entries are still
inspected for unsafe file types, and changes to package search blockers invalidate
the selected stage. Full-tree v1 manifests remain supported.

Staging repeats feasibility checks and exact hashes under the existing lock and
limits, never overwrites a destination, and retains incomplete copies on failure.
Discovery, fit plans and staging all report `proofs_verified=0`; they cannot
authorize training teachers, promotion or score claims. Native proof checks in
the unchanged sandbox remain mandatory afterward.

### September 23 closure feasibility result

The [generated receipt](papers/completion/lean_refactor_arena/evidence/import-closure-core-2026-09-23.json)
records discovery for the development problem `Core.InitsUpdatesComm`. Every
available external module was required: 80 on v4.27 and 71 on v4.29, including
StrataDDM. Removing editor/build bookkeeping alone was insufficient:

| Pin | Required payload, bytes | Conservative reservation, bytes | Result |
| --- | ---: | ---: | --- |
| v4.27.0 | 162,692,656 | 197,918,720 | DOES_NOT_FIT |
| v4.29.1 | 143,703,720 | 175,570,944 | DOES_NOT_FIT |

The per-stage cap remained 128,000,000 bytes, with 147,715,328 bytes of external
headroom. No selective stage was created. No private proof data, cache or old
receipt was removed; no cap, UID, FUSE permission, watcher budget or frozen
runtime changed. The watcher remains `ENVIRONMENT_FAILED`. Further isolated
reference controls need a separately reviewed storage/access design, not a
smaller proof claim or a negative training label for Leanstral.

Native fixture tests cover actual import discovery, unavailable prefixes and
already-imported targets on both pinned compilers. Offline tests cover exact
artifact families, scope drift, omitted-artifact drift, package shadowing,
read-only staging, malformed selections, deadlines, locks and budget refusal.
Native inventories are retained under
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/import-closure-v3jpourt/`;
the initial helper compile failures and six passing native fixture tests are
retained under the sibling `import-closure-s86kgxyk/` directory.

The authorized local allowance is **50 GB decimal**, with one isolated build
at a time. The implementation uses a sparse ext4 image of 49,799,999,488 bytes,
mounted with `fuse2fs`, and reserves 200 MB for bootstrap/metadata overhead.
Filesystem metadata reduces usable space further. A full filesystem rejects
writes with ENOSPC; this is not a periodic `du` watchdog. Compressed downloads,
extracted dependencies, build outputs, HOME, temporary files, caches and logs
all belong inside this same volume. Existing read-only toolchains/caches are
pre-existing storage, not new allocations against this allowance.

## Optional host requirements

Linux, `mke2fs`, `fuse2fs`, a working `/dev/fuse`, `findmnt`, and Docker with an
already installed compatible `ubuntu:24.04` image. The current host uses rootless
Docker. No system package installation, privileged container, host root mount,
Docker socket exposure, or image pull is used by the runner. A locally extracted
Ubuntu `fuse2fs` package is sufficient when its shared libraries are installed.
These tools are not Python/runtime dependencies of JevOps.

The container mounts host `/usr` read-only to use the existing Git/Python/system
tools. This assumes an ABI-compatible Ubuntu host/image; it is not a portable
container distribution. Its local image ID is recorded. The container root is
read-only, capabilities are dropped, privilege escalation is disabled, and only
explicit read-only source/toolchain mounts are added. Credentials and the host
HOME/environment are not passed through. Network is disabled unless
`--allow-downloads` is supplied. Limits request 4 CPUs, 16 GB memory, 512 PIDs,
and 16 MB shared memory; disk enforcement is the mounted filesystem, not Docker's
memory limit. This is isolation for trusted builds, not a claim that arbitrary
hostile kernel exploits or a malicious Docker daemon are contained.

## Commands

Choose a new task-owned root. Never initialize over an existing image:

```bash
python -m jevops.arena_prepare --root /owned/new-preparation --init \
  --fuse2fs /path/to/fuse2fs --max-bytes 50000000000

python -m jevops.arena_prepare --root /owned/new-preparation \
  --allow-downloads --readonly /prepared/read-only-cache \
  --readonly /path/to/installed/toolchains --timeout 1800 \
  -- /bin/bash -euc 'git clone --no-hardlinks --no-checkout /prepared/read-only-cache projects/project; ...'
```

Use exact corpus Git commits and exact installed Lean executables, not nearby
versions or moving branches. Change `origin` only in the new clone to its real
upstream URL. Lake fetches the pinned lockfile dependencies. A target such as
`lake --no-cache build +Strata.Languages.Core.StatementSemanticsProps:deps`
builds imports needed for the native prefix check without importing the theorem
under test. Set PATH explicitly to the pinned toolchain's `bin` for Lake children.
Missing toolchains must be downloaded/extracted into the volume, not global
`~/.elan`; this runner does not silently install or substitute one.

For cache reuse, check **all** flattened lockfile revisions, then independently
copy matching packages into the isolated project's `.lake/packages`. No writable
hardlinks, shared worktrees, or outside-project package symlinks. Revalidate the
new project with `lake_environment`; recompilation and native checking are still
separate operations. No `lake update` is required for a pinned lockfile.

Export a native-verifier manifest after preparation:

```bash
python -m jevops.arena_prepare --root /owned/new-preparation --export-projects \
  --state-root /prepared/track1-lake \
  --project-root /owned/new-preparation/work/projects/project \
  --output /owned/new-preparation/work/projects.json

TMPDIR=/owned/new-preparation/work/tmp python -m jevops.arena_lean --baseline \
  --projects /owned/new-preparation/work/projects.json --max-processes 36 \
  --timeout 120 --output /owned/new-preparation/work/baseline.json

python -m pytest -q --test-seal=off tests/test_arena_prepare.py
```

Each new root must uniquely match a corpus repository/revision. Export checks
Git cleanliness, toolchain declaration and dependency lock identities; it does
not claim compilation. Unavailable pins remain in the manifest. The native
verifier and controlled-trial runner themselves retain their documented trusted
local-execution boundary; they are not automatically sandboxed by exporting a
manifest. Setting TMPDIR keeps their scratch data inside the volume.

## Ownership, interruption and recovery

An OS `flock` is held throughout each command. A stable, workspace-specific
Docker name prevents a second container from starting if its supervisor died.
An existing named container is never automatically removed. Timeout and normal
cleanup check a per-invocation ownership label and remove only its immutable
container ID, never a foreign container that acquired the same name. Cleanup
failures are recorded explicitly. A hard-killed supervisor
can leave its container running. Inspect that container before recovery. Logs
are inside `work/logs`, with per-run JSON reports; a crash or full disk can leave
a log without a final JSON report. There is no automatic queue or background
continuous optimization service.

Before every run the runner checks the exact mount source/type, image inode,
image length and filesystem capacity. If the image is unmounted it fails closed
rather than writing into the underlying host directory. Bootstrap files are
checked against 180 MB, retaining 20 MB of the reservation for small Docker
metadata. Docker log persistence and image pulls are disabled. The writable
payload's cap is filesystem-enforced; the small external metadata reservation
is accounting headroom, not a system-wide host quota.

The FUSE daemon persists for later use. Unmount only when no build/check is
using the volume (`fusermount3 -u /owned/new-preparation/work`). Remount the same
image using the recorded fuse2fs binary and `-o rw,nosuid,nodev,fakeroot`.
`fakeroot` is needed for fuse2fs/Git's creation of initially read-only packfiles;
it affects permission checks inside this private volume, not host privileges.
An unclean shutdown may require an offline filesystem check. These are reusable
build artifacts, not transactional proof storage or a crash-consistent evidence
database. All native evidence identities must still be revalidated after changes.

### Timestamp integrity on the capped filesystem

The installed fuse2fs exposes whole-second change timestamps. An actual native
regression test reproduced stale stat-cache reuse after a same-size edit within
one second. `Fingerprinter` now re-reads content instead of using its stat fast
path for files with whole-second ctime. The isolated project artifacts therefore
incur additional hashing work; existing fine-grained host files can still reuse
their stat checks. Use strict hashing for other unreliable metadata sources.
Neither mode is a concurrent snapshot: keep prepared sources/artifacts stable
while verifying, and start a new context after changing them.

Full artifact hashing and cache extraction compete for FUSE metadata service.
During the September 22 continuation, a read-only Git status admission check
exceeded its 10-second timeout while cache files were being extracted; a busy
readiness inventory also reported one transient timeout. Neither observation
is semantic rejection. For further runs, serialize heavy inventory, native
tests and trials with preparation, not just builds. The same host lock can be
used explicitly (the native CLIs do not acquire it automatically):

```bash
flock -n /owned/new-preparation/single-build.lock \
  env TMPDIR=/owned/new-preparation/work/tmp \
  python -m jevops.arena_trial --run --problem Core.InitsUpdatesComm \
  --projects /owned/new-preparation/work/projects.json \
  --elan-home /owned/new-preparation/work/elan \
  --strategy proof_slice_unused_have --proposal-cap 2 \
  --repetitions 2 --max-calls 36 --timeout 120 \
  --progress --output /owned/new-preparation/work/new-trial.json
```

Wait for earlier native jobs that did not acquire this lock before using that
convention. `flock -n` refuses overlap rather than queuing an implicit retry.
Do not shorten fingerprints or bypass checkout validation to improve throughput.

## Read-only import staging (partial phase 1a)

`--stage-imports` copies explicit compiled-import directories into
`ROOT/import-stages/NAME`, outside the owner-only FUSE mount but **inside the
existing 200 MB external setup reservation**. It does not enlarge the image,
add a second allowance, remount FUSE with `allow_other`, change shared source
permissions, or change the verifier's UID/network/mount restrictions. Existing
compatible host toolchains remain read-only mounts; this mode does not stage
whole compilers or magically make a large Mathlib tree fit.

Inspect feasibility before requesting a copy:

```bash
python -m jevops.arena_prepare --root /owned/preparation --plan-imports \
  --stage-max-bytes 8000000 --timeout 120 \
  --import-dir /owned/preparation/work/project/.lake/build/lib/lean
```

Repeat the directories in the original resolution order, just as for staging.
`WOULD_FIT` (exit 0) means only that the observed metadata fits the requested
and remaining budgets. `DOES_NOT_FIT` (exit 1) reports reasons, payload bytes,
entry count, conservative required reservation and available setup headroom.
Zero allowance reports non-fit. No payload files are read or copied and no
bytes are reserved; `content_validated=false` and `proofs_verified=0`.
Invalid inputs or exceeding the entry/path/time bounds raise an error, never
a misleading partial-fit report. Inspection holds the shared preparation lock
and validates the mounted volume. Staging repeats inspection and content checks;
an earlier plan cannot authorize changed inputs. The staging path now also
rejects aggregate payload/reservation overruns **before hashing any files**.

```bash
python -m jevops.arena_prepare --root /owned/preparation --stage-imports \
  --stage-name imports-pin-epoch1 --stage-max-bytes 8000000 --timeout 120 \
  --import-dir /owned/preparation/work/project/.lake/build/lib/lean
```

Repeat `--import-dir` for every original search path, **in resolution order**.
The result is `STAGED_INPUTS_ONLY`, with `proofs_verified=0`, the manifest path,
manifest SHA-256, original/staged paths and reservation accounting. Save those
identities; they are not proof certificates. Output names must be new and are
never overwritten. The shared preparation lock covers inventory, reservation,
copy and validation. A busy lock fails rather than queuing overlapping work.

The default staging allowance is zero. A positive integer allowance up to
128,000,000 bytes is required, and the conservative reservation must also fit
the remaining **180 MB** external area after existing bootstrap/staged files
(20 MB stays reserved for Docker metadata). The copier counts and rounds every
file/directory allocation conservatively in 64 KiB units and reserves bounded
manifest space before writing. Sources have at most 4,096 entries, 64 roots,
128 MB payload, 32 path levels and a 1 MiB canonical manifest. The existing
post-copy allocated-block check also applies. This is controlled host-side
accounting, not a new filesystem quota or protection against unrelated host
writes; the large build payload still has its fixed filesystem-enforced cap.

Only regular files/directories are admitted: no symlinks, devices, FIFOs or
implicit traversal outside the named roots. Copies use fresh files, not
hardlinks; files become `0444`, directories `0555`, and the outer staging
namespace is caller-owned/private. Empty directories and full membership are
recorded. Source changes during copying prevent publication. A failed copy may
leave an incomplete owned directory for inspection; it still consumes headroom
and must not be accepted as a stage. There is no automatic deletion of user or
shared artifacts. Cooperative deadline checks bound scans/copy chunks but
cannot preempt a blocked filesystem operation; whole-run setup deadlines remain
a separate unfinished gate.

Bind the copy through the **existing original binding**, not a caller-supplied
replacement list of arbitrary libraries:

```python
staged_binding = original_binding.with_staged_imports(
    Path(result["manifest"]), result["manifest_sha256"])
# Construct a NEW NativeLeanVerifier/context using staged_binding.
```

The same interface is available to project manifests via the optional paired
fields `staged_imports_manifest` and `staged_imports_sha256`. Keep the existing
repository/pin/root/lockfile configuration, including `resolve_lake_manifest`.
The original resolver still determines all required imports and their order;
the manifest must match exactly. The Putnam resolver's existing restrictions
also remain in force. No source prefix, target, toolchain, dependency pin or
project-backed validation flag is replaced by staging.

Before and after native work, `ProjectBinding.fingerprint` rechecks the canonical
manifest against its externally supplied SHA-256 and both complete trees against
the recorded exact bytes. Modified originals, modified copies, writable copies,
hardlink sharing, wrong roots/order, malformed typed entries and extra files
fail closed. Stage identity participates in the immutable dependency context;
restaging or changing imports requires a new context, not reuse of old receipts.
This intentionally retains potentially expensive source rehashing. Read-only
modes do not defend against a hostile host owner/daemon; original prepared
artifacts, host and toolchains remain trusted.

### Staging validation, 2026-09-23

Fresh offline regression command:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=refresh \
  tests/test_arena_prepare.py tests/test_arena_projects.py tests/test_arena_isolation.py \
  tests/test_arena_lean.py tests/test_arena_replay.py tests/test_arena_source.py \
  tests/test_arena_pareto.py tests/test_arena_premises.py tests/test_arena_snapshot.py
# 557 passed, 123 skipped in 29.27s; zero reused, 443 fresh passes sealed.
```

This includes exact/zero/overflow budgets, occupied headroom, ownership/lock
boundaries, path/symlink/FIFO rejection, source/copy/manifest mutation, typed
manifest forgery, hardlink rejection, source mutation during copy, CLI defaults,
and staged binding/context validation. The native tests remained opted out.

The new opt-in canary compiled one trusted synthetic `StageFixture.lean` using
the existing isolated build runner in the capped FUSE workspace. It then staged
that real `.olean` and used it to check `staged_sample` through the existing
rootless verifier, without mounting the FUSE source into the UID-65534 worker.
It returned one `VERIFIED` receipt with no axiom expansion; this is not an Arena
problem or proof that arbitrary source/metric reports are trustworthy.

Native execution used the frozen source copy
`/tmp/jevops-import-stage-native-GDfZ90/source-v2` (123 files / 3,302,630 bytes),
manifest SHA-256
`d29b2f0f2230e2e6368c9faf576249487372e231bc7ff71ba63e9166842ea970`.
From that directory:

```bash
env PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/tmp/jevops-import-stage-native-GDfZ90/source-v2 TMPDIR=/tmp \
  JEVOPS_ARENA_DOCKER_TESTS=1 \
  JEVOPS_ARENA_PREPARATION_ROOT=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  JEVOPS_ARENA_DOCKER_SOCKET=/run/user/1000/docker.sock \
  JEVOPS_ARENA_DOCKER_IMAGE=sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517 \
  ELAN_HOME=/home/barberb/.elan \
  python -m pytest -q -s -x --test-seal=refresh \
  -o cache_dir=/tmp/jevops-import-stage-native-GDfZ90/cache-v2 \
  --basetemp=/tmp/jevops-import-stage-native-GDfZ90/tests-v2 \
  --junitxml=/tmp/jevops-import-stage-native-GDfZ90/canary-v2.xml \
  tests/test_arena_isolation.py -k live_prepared_fuse
# 1 passed, 68 deselected in 4.28s; zero seal reuse.
```

The canary acquires the same exclusive lock separately for its build, staging,
and verification; do not wrap it in a second non-reentrant acquisition. Its
source/stage names are private and unique. Both native opt-in and an explicit
preparation root are required. It downloads nothing and invokes no model.

The [saved generated report](papers/completion/lean_refactor_arena/evidence/native-import-staging-canary-v4.26.0-2026-09-23.json)
records a 1,507,328-byte staging reservation and total external preparation
overhead of 28,291,072 bytes, within the unchanged cap. It keeps a null official
score and false promotion/source-execution/metric-integrity authority flags.
The earlier development snapshot also passed this same canary (8.00 seconds);
the two overlapping executions used two trusted fixture builds and two verifier
attempts in total, not two distinct task results. The final snapshot verified
unchanged, and seven relevant implementation/test files matched the checkout.
The full repository suite and real corpus controls were not run for this slice.
Larger libraries/toolchains, all-pin isolated corpus compatibility, authenticated
costs and the other phase-1 release gates remain open.

### Real-project control and staging preflight, 2026-09-23

The new metadata-only preflight checked the exact Lake-resolved import paths
for two prepared Strata pins, not arbitrarily selected subsets. The
[generated inspection](papers/completion/lean_refactor_arena/evidence/import-staging-preflight-strata-2026-09-23.json)
contains no content validation or proof claims:

| Pin | Files | Payload bytes | Conservative copy reservation | Result |
| --- | ---: | ---: | ---: | --- |
| v4.27.0 | 880 | 167,341,758 | 274,137,088 | DOES_NOT_FIT |
| v4.29.1, including StrataDDM | 781 | 147,651,635 | 242,810,880 | DOES_NOT_FIT |

The caller allowance was 128,000,000 bytes, and remaining external setup
headroom was 151,672,064 bytes. This headroom is separate from free space inside
the existing FUSE image; unused image capacity cannot authorize a second host
allocation. Neither tree was copied, truncated, rebuilt or permission-modified.
Reproduce each row with `--plan-imports --stage-max-bytes 128000000` and its
reported `source_paths` as repeated `--import-dir` arguments. No failed plan
grants permission to omit mandatory compiled inputs.

A separate, already host-readable checkout enabled a **real corpus original**
control: `Core.InitsUpdatesComm`, Strata v4.26.0, commit
`451e5f047bafa010d178856db76c00029bfa4d7f`. The
[saved native receipt](papers/completion/lean_refactor_arena/evidence/native-isolated-original-core-v4.26.0-2026-09-23.json)
is `VERIFIED`, with preserved type and the same axiom set in both branches
(`Quot.sound`, `propext`, `Classical.choice`). It used UID 65534, no network,
read-only inputs, one CPU, 2 GiB memory, 64 PIDs and the existing pinned image.
Only compiler binary/library, driver and compiled import directories were
mounted; no FUSE source or broad home mount was exposed. No new build was needed
for this control. It covers **one of the task's three required pins**, not the
full corpus or the newer FUSE-backed pins.

This was the unchanged original as candidate: 224 reference tokens, raw
heartbeats 4,689,131 in the reference branch and 4,689,121 in the candidate
branch. The ten-unit difference is not a claimed optimization. This is the
existing two-branch measurement, not a fresh-process cold comparison or a
precommitted noise estimate. Official score remains null, promotion stays off,
and source-execution/metric-integrity authority flags remain false.

The runnable opt-in control is `test_live_project_original_control`. Its default
task/pin above can be explicitly changed with `JEVOPS_ARENA_CONTROL_PROBLEM` and
`JEVOPS_ARENA_CONTROL_TAG`; it never substitutes a different pin. The explicit
project manifest and preparation root are required. It locks the whole native
control and writes a new report under `work/logs`, including failures returned
by the adapter before asserting success. Do not wrap it in another `flock`.

Both native checks used the frozen source copy
`/tmp/jevops-project-control-tPmk3u/source` (127 files / 3,477,928 bytes), manifest
SHA-256 `b1720199eea56c27e9bec42c6346482b6040bd2af6c23447d96498b2378d8c1b`.
From that directory, the actual control command was:

```bash
env PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/tmp/jevops-project-control-tPmk3u/source TMPDIR=/tmp \
  JEVOPS_ARENA_DOCKER_TESTS=1 \
  JEVOPS_ARENA_PREPARATION_ROOT=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  JEVOPS_ARENA_CONTROL_PROJECTS=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/projects-prepared-20.json \
  JEVOPS_ARENA_DOCKER_SOCKET=/run/user/1000/docker.sock \
  JEVOPS_ARENA_DOCKER_IMAGE=sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517 \
  ELAN_HOME=/home/barberb/.elan \
  python -m pytest -q -s -x --test-seal=refresh \
  -o cache_dir=/tmp/jevops-project-control-tPmk3u/cache \
  --basetemp=/tmp/jevops-project-control-tPmk3u/tests \
  --junitxml=/tmp/jevops-project-control-tPmk3u/control.xml \
  tests/test_arena_isolation.py -k live_project_original_control
# 1 passed, 69 deselected in 6.96s; zero seal reuse.
```

The synthetic staging canary was rerun from the same snapshot with
`-k live_prepared_fuse`, `--basetemp=.../staging-tests`,
`--junitxml=.../staging.xml`, and without `JEVOPS_ARENA_CONTROL_PROJECTS`.
It passed (1 passed, 69 deselected in 4.35s); its
[generated follow-up report](papers/completion/lean_refactor_arena/evidence/native-import-staging-followup-v4.26.0-2026-09-23.json)
retains `arena_problem=false`. This continuation used one trusted fixture build
and two verifier attempts total, with no overlap, downloads or model calls.
The snapshot verified unchanged afterward; no owned containers remained.
The preparation image and 50 GB allowance were not changed.

Fresh offline regression command:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=refresh \
  tests/test_arena_prepare.py tests/test_arena_projects.py tests/test_arena_isolation.py \
  tests/test_arena_lean.py tests/test_arena_replay.py tests/test_arena_source.py \
  tests/test_arena_pareto.py tests/test_arena_premises.py tests/test_arena_snapshot.py
# 568 passed, 124 skipped in 25.21s; zero reused seals.
```

The added cases test metadata-only inspection, exact/zero caller allowances,
invalid limits, oversized aggregate payloads, reservation failures before any
hash/copy, changed inputs after planning, lock contention, bounded partial
inventories, deadlines and CLI exit semantics. The full repository suite was
not run. Full-size compiler/import storage compatibility, all-pin isolated
controls, authenticated measurement and automatic promotion remain open.
