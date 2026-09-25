# Native Arena measurement adapter

This is the next implementation slice of the
[improvement plan](LEAN_REFACTOR_ARENA_IMPROVEMENT_PLAN.md), not a competition
result. It reuses `ArenaEvaluator`, `VersionPin`, the axiom admission contract,
canonical content hashes, and the existing dependency `Fingerprinter`.
`RouterTuningLoop` continues to consume the same injected evaluator. No separate
agent framework, provider integration, or additional package dependency is added.

## Commands

```bash
# Read-only inventory. No Lean execution, network, or model calls.
python -m jevops.arena_lean --readiness

# Inventory the existing harness layout at an explicitly supplied path.
python -m jevops.arena_lean --readiness --state-root /prepared/track1-lake

# Actual native Lean on a tiny non-Arena proof. Requires this installed tag.
python -m jevops.arena_lean --smoke --tag v4.26.0 --max-processes 2

# Default tests work without Lean; integrations are explicitly opt-in.
python -m pytest -q --test-seal=off tests/test_arena.py tests/test_arena_lean.py tests/test_arena_projects.py
JEVOPS_ARENA_NATIVE_TESTS=1 python -m pytest -q --test-seal=off tests/test_arena_lean.py tests/test_arena_projects.py
```

All commands emit reports or tests, not submissions. The native CLI's process
budget defaults to **zero**. Exit zero means the JSON report was produced;
inspect individual outcomes, not the process exit status, for verification.
Core tests do not install Lean or access APIs. Native tests exercise explicitly
installed 4.26.0 and 4.34.0; missing installations are skipped, not substituted.

## Preparing a corpus baseline

Supply a JSON array of project bindings. Paths must refer to already prepared
checkouts and compiled import roots; the adapter does not run Lake or build them.
For example, replacing these illustrative paths with actual local paths:

```json
[
  {
    "repository": "https://github.com/strata-org/Strata",
    "lean_tag": "v4.26.0",
    "git_commit": "451e5f047bafa010d178856db76c00029bfa4d7f",
    "root": "/prepared/Strata-v4.26.0",
    "search_paths": [
      "/prepared/Strata-v4.26.0/.lake/build/lib/lean",
      "/prepared/Strata-v4.26.0/.lake/packages/dependency/.lake/build/lib/lean"
    ]
  }
]
```

List each actual dependency import directory in its intended resolution order;
there is no implicit ambient `LEAN_PATH` or Lake environment. The example's
`dependency` is a placeholder, not a claim about Strata's dependency names.

```bash
python -m jevops.arena_lean --readiness --projects /prepared/projects.json
python -m jevops.arena_lean --baseline --projects /prepared/projects.json --max-processes 36
```

The baseline report retains one row for every required problem/version, including
unavailable rows. A missing project binding, wrong commit, tracked modifications,
missing pin/import, or ambiguous source location never silently falls back to a
different environment. No project file is modified. Original source must occur
exactly once in the pinned file; only the preceding source is elaborated, not
later declarations or the original target module. Per-version baselines have
separate contexts and are not aggregated into an allegedly complete score.

Alternatively set `"resolve_lake_manifest": true` instead of `search_paths` in
a project binding. The adapter reads Lake lockfile versions **1.1.0/1.2.0**,
checks every flattened Git dependency's exact revision and tracked cleanliness,
and derives import roots from existing `.lake/build/lib/lean` directories.
Escaped names such as `«doc-gen4»` resolve to their actual package directory.
Unknown schemas, path dependencies, duplicate names, floating revisions and
paths escaping the project are rejected. Unbuilt tooling packages are not
automatically imported. A valid lockfile is not evidence that all required
imports are available, or that cached binaries were faithfully built from it.
Native execution is still required. Explicit legacy search-path bindings remain
supported and content-bound, without claiming their Git revisions were audited.
Git metadata checks disable optional locks/index refreshes; even inventory must
not rewrite the shared checkout's index as a side effect of `git status`.

### File-less Putnam bindings

The vendored organizer [benchmark schema](papers/completion/lean_refactor_arena/space/benchmark.py)
identifies Putnam `version_info` hashes as **Mathlib4 commits**. The adapter now
supports these rows directly, using the exact JSONL `header` as the prefix:

```json
[
  {
    "kind": "putnam",
    "repository": "",
    "lean_tag": "v4.26.0",
    "git_commit": "2df2f0150c275ad53cb3c90f7c98ec15a56a1a67",
    "root": "/prepared/putnam_lake/v4.26.0"
  }
]
```

The root need not be a Git checkout. Its exact toolchain and lockfile are
required; Mathlib's actual checkout must match the JSONL commit, and Aesop and
transitive dependencies must match the lockfile. The Mathlib/Aesop package URLs
are checked. Neither `pins.json`, a release tag, nor a `BAKED` marker can replace
these checks. Mathlib and Aesop root oleans must be present before attempting a
baseline (this is only a presence check, not validation of their full import
closure). Extra search paths are refused. The cached `Putnam.Candidate` module
is not imported or edited; no theorem from it is offered as its own proof.

`ProjectBinding.fingerprint()` rechecks lockfile identity and dependency Git
state before cache use and after execution. Changes require a new binding and
measurement context. The old project materializer also now propagates an
explicit `jsonl_version_pin` into its Mathlib requirement instead of silently
replacing it with a tag; tag-only callers remain compatible. Existing projects
are **not** automatically rewritten or rebaked.

### Existing harness cache inventory

`--state-root` is an alternative to `--projects`, not an ambient home-directory
search. It maps required pins to `clones/github.com/<owner>/<repo>` and
`putnam_lake/<tag>` under that exact root. Every required version is retained;
the currently checked-out HEAD is never substituted for a missing historical
revision. The report includes the generated `projects` array for auditing.

```bash
python -m jevops.arena_lean --baseline \
  --state-root /prepared/track1-lake --max-processes 12 --timeout 90 \
  --output /prepared/new-baseline.json
```

`--output` also saves the JSON report, refusing to overwrite an existing file.
Reports are written on completion, not crash-resumable incremental checkpoints.
The baseline shares an explicitly owned per-run file-hash cache across rows;
membership and applicability are still rechecked and no verifier receipt is
reused as a new invocation. Fingerprint reads/stat hits are reported separately
from native processes. Project provisioning/building remains separate work.

## Evidence and metrics

`jevops/lean/ArenaCheck.lean` is trusted instrumentation executed by the pinned
Lean binary. Its declarations are **not added to the candidate environment**.
It imports the source's original imports at trust level zero, processes the
pre-theorem commands, and requires the exact target name to be absent. The
reference and candidate then elaborate independently from that same state.
The reference proof is never offered to the candidate as an assumption.

### Preserve frontend errors before judging a proof

Lean's [per-command elaborator](https://github.com/leanprover/lean4/blob/v4.27.0/src/Lean/Elab/Command.lean)
resets its message log. The driver now keeps prefix diagnostics outside that
reset and stops immediately on header, import, parser or earlier-command errors.
It also rejects a recovered reference/candidate parse before elaboration and
reports both reported and unreported messages. Invalid prefixes are
`UNAVAILABLE/prefix_errors`, not proof successes or negative prompt labels.
Type equality, axiom rules, heartbeat limits, private-import visibility and
independent branches are unchanged.

This closes a reproduced admission bug: an invalid earlier declaration followed
by a valid namespace command could previously lose its error and let a later
proof be reported as verified. The kernel still checked that later proof, but
the complete prefix had not passed. Old receipts are not retroactively
re-certified; the changed driver hash requires fresh contexts and measurements.

The same repair exposed the watcher's misleading `reference_target_missing`
on Strata v4.27.0. The identical original proof passes on the host, while the
isolated run now reports the actual import error: `Strata` is unavailable in
`/deps/0`. This is an environment failure, not evidence against Leanstral.
The driver's theorem lookup did not need to be weakened. The earlier hypothesis
about a public theorem view was not supported by the diagnostic.

Fresh metadata-only staging plans for the complete v4.27.0/v4.29.1 import trees
require approximately 274 MB/243 MB of conservative reservation, versus about
148 MB of remaining external staging headroom. The capped filesystem itself
still has free space; the restriction is the existing sandbox-readable staging
allowance. Neither full-tree copy was attempted. No cache was removed, cap
enlarged, FUSE permission relaxed, or worker privilege changed. A different
storage-safe import layout must be reviewed before resuming native evaluation.

Diagnostic sources, before/after reports and fresh regression-test receipts are
retained under
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/native-visibility-ibrTKK/`.
`tests/lean/ArenaTargetProbe.lean` is a diagnostic tail assembled with the
trusted driver library, not a standalone verifier or a source of training labels.
The original watcher remains on its frozen runtime and environment-failure gate;
it was not restarted, given extra budget, or supplied new teachers.
After the repair, 18 focused native tests passed on v4.27.0/v4.29.1, two
compatibility tests passed on v4.26.0, and two v4.34.0 checks skipped because
that toolchain was unavailable at the supplied location. The broad offline
suite passed 545 tests with 124 opt-in skips; all runs bypassed test seals.

Run the focused installed-toolchain regressions explicitly:

```bash
JEVOPS_ARENA_NATIVE_TESTS=1 python -m pytest -q --test-seal=off \
  tests/test_arena_frontend_errors.py tests/test_arena_module_audit.py
```

Acceptance requires a theorem with the expected name, successful elaboration,
closed proof, identical universe-parameter lists and structurally equal native
types, plus transitive axiom lists within the context's explicit policy. Type
equality is deliberately stricter than definitional equivalence. It catches,
for example, a refactor accidentally dropping an implicit section parameter
even when the textual goal still looks like `True`. Instrumentation disables
asynchronous elaboration and kernel-check bypass/debug-sorry options. Local
intake restrictions still apply; compilation success alone cannot admit a row.
Parenthesized Mathlib cardinality notation `#(...)` is supported: one frozen
ArkLib reference uses it. Diagnostic commands (`#eval`, `#print`, `#check`, etc.)
remain forbidden. All 15 frozen references have an offline intake regression;
passing it is not compilation evidence.

For a `module` prefix, exported imports can represent ordinary theorems as
axiom-shaped constants with hidden proof bodies (see Lean's
[module import implementation](https://github.com/leanprover/lean4/blob/v4.27.0/src/Lean/Environment.lean)).
The driver loads the same pinned imports' private data into an **audit-only**
environment. It traverses the checked local proof, expanding an imported opaque
view only when the imported declaration's type and universe parameters match
exactly. Genuine axioms, including those used inside hidden private helpers,
remain subject to the unchanged allowlist. Missing or mismatched audit data
cannot admit a proof. Neither elaboration branch receives this private audit
environment; private declarations remain inaccessible to candidate code.
This fixes a reproduced Strata v4.27 false rejection without treating standard
theorem names as additional trusted axioms. Driver changes invalidate old
context identities. The audit remains outside the heartbeat measurement span.

Heartbeat scope is **one command's synchronous elaboration**, including its
type elaboration and declaration checking, excluding prefix import/elaboration,
candidate parsing and final axiom collection. The raw counter delta and its
integer quotient by 1000 are both reported. These are not milliseconds, pure
kernel time, or authenticated organizer measurements. Reference and candidate
execute sequentially in independent environment branches of one process;
process-wide caches can affect raw counts. Even identical sources need not
have identical raw deltas. Repeated pilot measurements and official calibration
are still needed before performance claims.

The default is still `reference-first`. The adapter also supports explicit
`branch_order="candidate-first"`, bound into the immutable options and native
report. Each branch still starts from the independent prefix state. The
[controlled trial runner](ARENA_CONTROLLED_TRIALS.md) balances both orders with
unchanged controls and fresh processes; it does not turn an uncalibrated native
observation into an organizer score or loosen score-aware router admission.

`NativeLeanVerifier.calibrate(context)` reserves a native invocation and creates
a new immutable context with a locally measured reference denominator. Failure
returns no calibrated context plus an explicit receipt. `.evaluator(context,
max_calls=...)` requires that denominator; do not inject published worker
heartbeats as if they used this method. Subsequent native requests remeasure the
reference and report drift as `ERROR`/incomplete rather than silently scoring it.
The reference raw count is retained for inspecting quantization/noise.

Outcome meanings:

- `VERIFIED`: all native/type/axiom checks passed under the declared environment.
- `REJECTED`: this candidate failed elaboration/type/intake/axiom checks; not a
  disproof of its theorem or evidence that every possible refactor fails.
- `UNAVAILABLE`: a required environment/import is unavailable.
- `TIMEOUT`: wall-clock or recognized heartbeat exhaustion; not semantic rejection.
- `BUDGET_EXHAUSTED`: no native invocation units remain.
- `ERROR`: invalid reference, stale environment, report mismatch, calibration
  drift, malformed instrumentation, or another infrastructure/invariant failure.

The evaluator maps missing/nonterminal outcomes to `INCOMPLETE` and a null score.
The corpus baseline CLI intentionally leaves the combined score null regardless
of the measured rows. All reports leave `official_score` null.

## Router integration

Create explicit `project_binding(record, pin, project, elan_home)` instances for
every listed version and pass the mapping to `NativeLeanVerifier`. The adapter
exposes `context(record)`, `calibrate(context)`, and `evaluator(context, max_calls)`.
Pass that evaluator into the existing `RouterTuningLoop` with
`RouterTuningConfig(selection_objective="arena-v1", train=False)` and an explicit
offline `router_generate` callback. Never omit the callback if live inference
is not intended. Default shortest-proof behavior and the frozen `LRA/v1` Lake
admission/proxy paths are unchanged.

Calibration and candidate checks share the adapter's `max_processes` budget.
Each native invocation may elaborate both reference and candidate and costs one
invocation unit, not one declaration. The evaluator separately limits requests.
Transient results are not cached; cached terminal receipts are observations from
the old invocation, not new independent checks or extra charges.
Constructing `ArenaEvaluator(..., evidence_mode="local_lean")` without an
applicability validator disables receipt reuse: the verifier must run again.
The adapter's `.evaluator()` helper supplies that validator explicitly.

## Trust, resources, and limitations

Toolchain binaries, serialized imports/IR, shared libraries, source prefixes,
project configuration and explicit search roots are content-bound. The
adapter, Lean driver, intake/axiom checks, canonical serializer, version-record
implementation and fingerprinter are also included in the boundary identity.
Changing those files requires a fresh measurement context, even when a model's
candidate text and the underlying project revision have not changed. The
fingerprinter rescans membership and uses inode/ctime-aware hash reuse; strict
byte rehashing is available with `strict_hashes=True`. Preparation/global scans
can be expensive on large libraries and are not counted as Lean invocations.
Applicability is checked before receipt reuse and again after subprocess work.
Changed dependencies require a new binding/adapter/context; old historical
receipts are not evidence about the changed environment.

This assumes a trusted local toolchain/OS and exclusive, stable ownership of
project/dependency files during a request. Before/after fingerprints are **not
atomic filesystem snapshots** and do not protect against adversarial transient
modification. Standard system libraries and the OS are trusted platform inputs;
hashes are identity checks, not signatures or proofs. No cross-process locking
or distributed-safety claim is made.

Default execution uses a private temporary working directory and a minimal environment,
without inherited credentials or ambient Lean paths. Input, combined output,
wall time, heartbeats and invocation counts are bounded; process-group cleanup
only kills children of this invocation. **This is not an OS security sandbox**:
trusted imported metaprograms may perform IO, access the filesystem or network,
or expect a project working directory. Run only trusted local inputs here, or
use the explicit profile below for host isolation. Independent proof/report
authority, currency quotas, official worker parity and full-corpus calibrated
optimization remain future work. No benchmark improvement is established by
the toy smoke test.

## Optional rootless Docker execution

The default profile described here uses container UID/GID 65534. A separate
[opt-in mount-owner profile](ARENA_MOUNT_OWNER_PROFILE.md) is available for
owner-only FUSE inputs; it changes the namespaced UID, not the storage limit,
and requires fresh isolation validation. No automatic fallback was added.

`arena_isolation.DockerIsolation` is an injected execution policy for the same
`NativeLeanVerifier`, not a second verifier or search framework. The native CLI
supports it in `--smoke` and `--baseline`; trial/selection CLIs have not been
silently switched. Programmatic callers can inject an isolated verifier through
their existing verifier factory. Readiness remains inventory, not a sandbox test.

With an explicitly selected **already installed** minimal Linux image, local
rootless Docker socket and readable pinned toolchain:

```bash
python -m jevops.arena_lean --smoke --tag v4.26.0 \
  --elan-home /path/to/elan --max-processes 2 --isolation docker \
  --docker-socket "$ARENA_DOCKER_SOCKET" --docker-image-id "$ARENA_DOCKER_IMAGE"
```

Set `ARENA_DOCKER_SOCKET` to an absolute caller-owned Unix socket and
`ARENA_DOCKER_IMAGE` to its full local `sha256:` image ID, not a tag. The profile
never installs Docker, downloads images/toolchains, runs Lake, or connects to an
ambient Docker context/remote daemon. Rootless mode, seccomp, private cgroup v2
and CPU/memory/swap/PID controls are mandatory. Unsupported platforms fail closed.
Image implicit volumes or extra environment variables are refused.

Each invocation creates a uniquely owned container, inspects its effective
configuration **before starting**, then removes only its exact ID after checking
the owner label. Default limits are one CPU, 2 GiB memory, no additional swap,
64 PIDs, and a 64 MiB noexec `/tmp`. The worker is UID/GID 65534, has no capabilities,
uses `no-new-privileges`, a read-only rootfs and no network. Only the pinned Lean
executable, toolchain libraries, driver and explicitly bound import directories
are mounted, read-only. Docker's special `/etc` network files are overridden by
read-only empty files. No home, repository root, daemon socket, credentials or
host configuration are mounted. Minimal environment and bounded stdout/stderr
are retained; container log storage is disabled. This is not a ban on all
subprocesses: programs supplied by the trusted image may run within those limits.

The image, policy, Docker executable content and socket identity are bound into
the verification context; changing them requires a new adapter/context. Existing
intake, type/axiom, dependency, calibration and receipt checks still apply. Zero
invocation budget runs no Docker or Lean process. The existing `processes` counter
reserves attempts **before preflight**; missing infrastructure can consume a unit
without Lean starting. Cache hits do not rerun containers or constitute new checks.
Unavailable infrastructure is `UNAVAILABLE`; cleanup/effective-policy violations
are `ERROR`, never successful proofs. Invocation wall time covers Docker setup
and attached execution, with an additional bounded 15-second cleanup allowance.
Dependency setup/fingerprinting still has no whole-run deadline.

Limits and remaining trust:

- Trust the daemon, Linux kernel, immutable image and explicit compiler/imports.
  Read-only binds are not snapshots against concurrent host writes. The daemon
  and host platform are trusted, not comprehensively fingerprinted.
- Candidate metaprograms and measurement/checking still share one Lean process.
  `separate_proof_checker` is explicitly false. Arbitrary metaprograms can still
  threaten proof/report/metric integrity; automatic production promotion stays off.
- Supervisor SIGKILL or daemon failure can leave a resource-capped worker.
  Normal timeout/output/error cleanup is tested, but this is not crash recovery
  or cross-process locking. Cleanup failures report the owned name/ID for audit.
- Non-root workers require readable mounted files. The current preparation
  FUSE volume denies that access; using it returned a permission error, not a
  proof. [Explicit small-import staging](ARENA_PREPARATION.md#read-only-import-staging-partial-phase-1a)
  can now supply independent read-only copies on compatible host storage, with
  both source and copy bytes checked at every binding fingerprint. A native
  FUSE-to-isolated-import canary passed. No UID-zero, `allow_other` or changed
  source-permission fallback was added. A real original-proof control for
  `Core.InitsUpdatesComm` on the already host-readable Strata v4.26.0 checkout
  also passed under this profile; see the [control and staging preflight](ARENA_PREPARATION.md#real-project-control-and-staging-preflight-2026-09-23).
  That control does not exercise large FUSE copies. Large toolchains/libraries and full
  prepared-corpus isolation still require compatible provisioning and fresh checks.
- Default scratch bounds concern `/tmp`; container device filesystems are also
  present and charged under the memory cap. This is not a currency budget.

### Isolation validation, 2026-09-23

The installed Bubblewrap probe could not create its isolated loopback interface;
no system setting was changed. Rootless Docker with the existing Ubuntu 24.04
image below worked. Tests used synthetic canaries, not actual credentials.
The live suite checks read-only inputs/driver, hidden host canary/socket, absent
inherited fake credentials, inaccessible host loopback, distinct network namespace,
actual cgroup memory/swap/CPU/PID settings, seccomp/no-new-privileges/no capabilities,
writable private scratch, valid/wrong-type/unproved targets in both branch orders,
and owned cleanup after timeout/output overflow. These finite checks are not a
claim of an unhackable sandbox.

The saved [isolated smoke receipts](papers/completion/lean_refactor_arena/evidence/native-isolated-smoke-2026-09-23.json)
contain two VERIFIED native checks on Lean 4.26.0, no live model calls and a null
official score. This is the non-Arena toy theorem, not new optimization evidence.
Recorded command (the existing single-build lock serialized all native work):

```bash
flock -n /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/single-build.lock \
  env TMPDIR=/tmp python -m jevops.arena_lean --smoke --tag v4.26.0 \
  --elan-home /home/barberb/.elan --max-processes 2 --isolation docker \
  --docker-socket /run/user/1000/docker.sock \
  --docker-image-id sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517 \
  --output papers/completion/lean_refactor_arena/evidence/native-isolated-smoke-2026-09-23.json
```

Default tests never contact Docker. Live integrations need their own explicit
`JEVOPS_ARENA_DOCKER_TESTS=1`, image/socket and `ELAN_HOME`; opting in with missing
Docker prerequisites fails rather than silently skipping or executing on the
host. `JEVOPS_ARENA_NATIVE_TESTS=1` alone does not enable Docker tests.

Final native/Docker regression command: **143 passed, 48 skipped in 76.53 s**.
The skips were the existing native tests for tags 4.25.0, 4.28.0 and 4.33.0-rc2
absent from the explicitly selected host `ELAN_HOME`; no version was substituted.
Docker's nine live tests all ran (4.26.0). Default native tests also exercised
installed 4.26.0 and 4.34.0. No owned check containers remained afterward.

```bash
flock -n /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/single-build.lock \
  env TMPDIR=/tmp JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_ARENA_DOCKER_TESTS=1 \
  JEVOPS_ARENA_DOCKER_SOCKET=/run/user/1000/docker.sock \
  JEVOPS_ARENA_DOCKER_IMAGE=sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517 \
  ELAN_HOME=/home/barberb/.elan python -m pytest -q -rs --test-seal=off \
  tests/test_arena_isolation.py tests/test_arena_lean.py
```

Broader offline regression: **587 passed, 111 skipped in 3.79 s**:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=off \
  tests/test_arena.py tests/test_arena_isolation.py tests/test_arena_lean.py \
  tests/test_arena_projects.py tests/test_arena_module_audit.py tests/test_arena_trial.py \
  tests/test_arena_pareto.py tests/test_arena_report_audit.py tests/test_arena_snapshot.py \
  tests/test_arena_compositions.py tests/test_arena_rules.py tests/test_arena_prepare.py \
  tests/test_arena_recovery_evidence.py
```

These suites overlap; their counts are not additive unique coverage. This was
not a full-repository test run. No downloads, builds or API calls were made;
the preparation filesystem stayed below the authorized 50 GB cap.

## Proof-data replay follow-up

The optional [two-stage replay diagnostic](ARENA_TERM_REPLAY.md) now reuses this
adapter's trusted challenge and isolation policy, plus the existing expression
DAG codec. Its fresh checker process kernel-checks bounded exported terms without
elaborating candidate source or loading candidate native artifacts. This has a
different result type from source verification: `PROOF_DATA_CHECKED` explicitly
does not establish source correspondence or measurement integrity and is never
converted into a `VersionReceipt`. Existing native/selector behavior is unchanged.
