# Isolated proof-data replay — partial phase 1b

`jevops.arena_replay.ArenaTermReplay` extends the existing native challenge and
isolation components with an **additional diagnostic**, not a new proof-source
admission rule or agent framework. It uses the same Lean kernel in a fresh
process; it is not an independently implemented kernel.

The selected local 4.26.0/4.34.0 toolchain inventories lack `leanexport`.
4.34.0 has `leanchecker`, but 4.26.0 does not. Rather than treating an untrusted
candidate `.olean` as a safe executable input, this slice reuses the repository's
bounded [structural expression codec](EXPR_DAG_CODEC.md). No toolchain is upgraded,
downloaded or substituted. Capability coverage is established by actual runs,
not by assuming current Lake documentation applies to historical pins.

## What executes where

1. The Python adapter freezes the existing `ArenaContext`, binding, checker code,
   resource limits and isolation identity. It reserves two invocation units before
   any worker starts.
2. An isolated producer elaborates the candidate in the target-free trusted
   prefix. It exports two closed expression DAG roots (proof and declared type),
   universe parameters and target identity. Its claimed verification flags,
   diagnostics and timings cannot authorize admission.
3. The parent validates bounds, canonical DAG structure, context/toolchain IDs,
   names, roots and envelope fields. Cyclic/forward references, unknown fields,
   duplicate JSON keys, non-finite numbers and oversized payloads fail closed.
4. A **different, fresh container/process** reconstructs the trusted prefix and
   original reference. It receives bounded proof data, never candidate source or
   native artifacts. It checks exact type/universe identity and kernel-checks a
   theorem declaration against the original target-free environment. The accepted
   axiom set must be permitted and a subset of the reference's set.

The checker uses `addDecl` with asynchronous elaboration and kernel-skip options
disabled, not `addAndCompile`. It does not evaluate the decoded proof as a tactic.
Imports, initializers, prefix and reference code remain **trusted challenge
inputs**, so this is not a general-purpose verifier for untrusted projects.
The same process/output/resource controls and ownership-checked container cleanup
apply to both stages. No shared mutable candidate volume connects the two.

`ArenaReplay.lean` is assembled with the existing library portions of
`ExprDAG.lean` and `ArenaCheck.lean`, using checked unique namespace delimiters.
Only the final replay entrypoint is included; no intermediate compiler build or
candidate `.olean` import is needed. Exact assembled bytes and source modules
are included in the replay identity, and changes between stages invalidate work.

## Deliberate limits and outcome meanings

`PROOF_DATA_CHECKED` means the exported term checks against the frozen challenge.
It **does not establish that the submitted source produced that term**. A hostile
producer can substitute another valid term for the same target; the live suite
demonstrates this by substituting a valid proof for an unproved `by skip` source.
In the default unrestricted diagnostic, the result still has `candidate_source_verified=false`,
`source_export_binding="UNESTABLISHED"`, `metric_integrity_established=false`
and `promoted=false`. Never translate this status into an Arena `VERIFIED`
source receipt, a search reward or a training success.

- `REJECTED`: elaboration, type/universe, kernel or axiom-policy failure; not a
  disproof of the target.
- `UNSUPPORTED`: this codec/boundary cannot represent or check the export. V1
  permits constants from the original prefix only, not new auxiliary declarations.
  Adding support requires checking those declarations rather than trusting them.
- `UNAVAILABLE`, `TIMEOUT`, `BUDGET_EXHAUSTED`, `ERROR`: distinct non-success
  infrastructure/resource/invariant outcomes. An unavailable checker never enables
  host fallback or successful admission.
- `FIXTURE_PROOF_DATA_CHECKED`: an explicitly injected offline test runner; no
  native kernel-check claim is made, and `proof_data_checked` remains false.

Reports retain the exact claimed candidate, challenge context, exported DAG,
content hashes, bounds and checker envelope. Content hashes identify data; they
do not authenticate a producer or prove export/source correspondence. The reused
execution profile's `separate_proof_checker=false` still describes the legacy
native-source boundary; this report separately states
`separate_proof_data_checker=true`. Those are different claims.

Two units are reserved atomically by the single owner before work; failed producer
attempts do not refund the checker reserve. `process_attempts` counts stage/preflight
attempts, which can fail before Lean starts. Repeated evaluations require fresh
units: there is no receipt cache. Default budget zero and budget one launch nothing.
Each stage has its own bounded deadline and cleanup allowance; setup/fingerprinting
still lacks a whole-run deadline. This is not cross-process budget coordination.
Use the existing external single-build lock for native experiments.

The producer/checker use the existing non-root Docker profile. Prepared FUSE
imports still need compatible read-only storage; no shared permissions or worker
UID were changed to bypass that restriction. Automatic selection integration,
general source/export linkage, authenticated cold measurement, environment-delta accounting,
definition-equivalence checking and automatic production promotion remain deferred.

The cold-observation extension below now measures one branch per producer;
**authenticated cold costs and their use in production confirmation remain
deferred**. Do not read a measured counter as closure of those trust requirements.

## Runnable example

Use an existing rootless Docker socket, immutable local image ID and installed
host toolchain. No API, Lake build, model download or image pull is performed:

```bash
python -m jevops.arena_replay --smoke --elan-home /path/to/elan --tag v4.26.0 \
  --docker-socket "$ARENA_DOCKER_SOCKET" --docker-image-id "$ARENA_DOCKER_IMAGE" \
  --max-processes 2 --output /path/to/new-report.json
```

The CLI refuses to overwrite evidence. Exit zero means a JSON diagnostic report
was emitted, not that proof data or source was accepted; inspect `status`.
This smoke is a small non-Arena theorem, with a null official score and no measured
token/heartbeat improvement claim.

Offline tests run without Docker or Lean:

```bash
env -u JEVOPS_ARENA_DOCKER_TESTS -u JEVOPS_ARENA_NATIVE_TESTS \
  python -m pytest -q --test-seal=off tests/test_arena_replay.py
```

For live integrations set `JEVOPS_ARENA_DOCKER_TESTS=1`,
`JEVOPS_ARENA_DOCKER_SOCKET`, `JEVOPS_ARENA_DOCKER_IMAGE` and `ELAN_HOME`
explicitly and hold the single-build lock. Missing opted-in prerequisites fail;
they never silently switch to another toolchain or unisolated execution.

## Explicit-term structural gate — partial tickets 1b/1d

`ArenaTermReplay(..., source_policy=ExplicitTermPolicy(constants=(...)))` now
adds a source-derived structural gate to this same two-stage runtime. It is
opt-in; existing unrestricted diagnostics retain their previous behavior.
`jevops/arena_source.py` is a standard-library-only parser/matcher, not a new
Lean verifier, agent framework, or general Lean parser.

The accepted proof suffix is **exactly** ` := by exact TERM`, with this grammar:

```text
REF  ::= @local | @_root_.allowedConstant
TERM ::= REF | (REF TERM+)
```

Every reference uses `@`; application is explicit and parenthesized. An
application's entire left-associated spine stays in one group, for example
`(@_root_.And.intro @A @B @ha @hb)`. Nesting partial applications instead would
let Lean resume implicit argument insertion; the grammar rejects such heads.
For example, `theorem t (f : True -> True) (h : True) : True := by exact (@f @h)`.
The frozen statement must use single-name, explicit parenthesized parameters;
ASCII names, unique parameters and bounded sizes are required. Locals come from
those declaration parameters, **not** from names in the result type or untrusted
export. A goal `(h : True) -> True` does not make `h` available to `exact @h`.
Grouped/implicit parameters, default values, comments, arbitrary tactic syntax,
holes and trailing commands are unsupported. The matcher also rejects
autoImplicit/section-added parameters when the actual lambda structure differs.
Constants must be explicitly allowlisted and fully qualified via `_root_`; v1
rejects exported constant universe arguments rather than inferring them.

The parent parses the exact source before reserving work. After the ordinary DAG
validation it matches each declared parameter's lambda/name/binder annotation and
domain to the exported type, then checks exact local de Bruijn indices, constant
names and application structure. The only normalization is erasure of validated
expression metadata; no beta/delta/eta reduction or proof-irrelevant equality is
used. Thus another hypothesis of the same proposition cannot replace the claimed
one. Domain fingerprints compare data within one validated DAG, not theorem truth.
Matching is bounded by DAG size and the small source plan, not expanded tree size.

The fresh checker remains unchanged: it receives **no candidate source**, checks
the export's type against the frozen reference, kernel-checks the proof and
enforces the existing axiom policy. A forged export type cannot acquire authority
merely by making the parent match succeed. The full policy, its bounds and matcher
implementation participate in the immutable context; policy changes require a
new adapter/epoch and invalidate in-flight observations.

New outcome details:

- Unsupported syntax returns `UNSUPPORTED` before any reservation/launch; there
  is no permissive fallback.
- A structural substitution returns `REJECTED` with `source_export_mismatch:…`
  before the checker. Both reserved units remain charged; only the producer was
  attempted. This is a source/export mismatch, not a disproof of the target.
- `source_structure.structure_matches=true` records only the parent's structural
  match. It may coexist with a later kernel failure and is not proof admission.
- After **both** structural matching and native kernel success,
  `source_export_binding="EXPLICIT_TERM_STRUCTURE_CHECKED"`. Injected stage
  fixtures instead use `FIXTURE_EXPLICIT_TERM_STRUCTURE_CHECKED` and cannot set
  `proof_data_checked=true`.

This deliberately does **not** assert execution or cost correspondence. In
particular, it does not audit imported parser/tactic implementations or show that
the producer actually elaborated the claimed bytes. An adversarial imported
elaborator is still outside this gate's assurance. Reports retain
`candidate_source_verified=false`, `source_execution_attested=false`,
`metric_integrity_established=false`, `promoted=false`, `training_enabled=false`
and a null official score. The narrower structural claim must not be translated
into a legacy source receipt, selection reward or training label. General
source/execution attestation and the rest of phase 1 remain open.

The optional CLI example is:

```bash
python -m jevops.arena_replay --smoke --explicit-source \
  --elan-home /path/to/elan --tag v4.26.0 \
  --docker-socket "$ARENA_DOCKER_SOCKET" --docker-image-id "$ARENA_DOCKER_IMAGE" \
  --max-processes 2 --output /path/to/new-explicit-report.json
```

This mode uses a trusted `@_root_.True.intro` reference and an `@h` candidate,
with the unchanged target `(h : True) : True`. It is a non-Arena integration
control, not an optimization result. Combine with `--cold --max-processes 16`
to measure the fixed eight-sample batch. Both arms must satisfy the same frozen
source policy **before** the batch reserves resources. Equal source-token counts
in this smoke are a neutral result; heartbeat observations remain unauthenticated.

The native regression suite also deliberately runs a *different* tactic program
that exports the same term as the claimed explicit source. Structural matching
succeeds, while execution/cost attestation stays false. This is retained evidence
of the remaining boundary, not a test that grants source authority.

## Cold, single-branch observations — partial ticket 1c

Construct `ArenaTermReplay(..., cold_measurement=True)` and call `evaluate(source)`
for one observation, or `cold_comparison(source, repetitions=2, seed=17,
noise_floor_raw=0)` for a precommitted one-pin comparison. The existing replay
adapter, structural codec, kernel checker, rootless isolation and
`arena_pareto.heartbeat_relation` are reused; legacy native/selector defaults
and the official score are unchanged.

The explicit method is `fresh-process-single-command-raw-heartbeats/v1`.
Each producer starts in a fresh container/process, reconstructs the trusted
prefix and elaborates **one** supplied theorem. It never elaborates the reference
first when measuring a different candidate. The existing branch counter surrounds
synchronous command elaboration and forced theorem value, **not** prefix/import
construction, parsing, export, the separate checker or process setup. Prefix
elaboration can still warm tactic state; OS page caches are not flushed. Thus
"cold" means no earlier reference/candidate branch in this process, not cold
hardware, filesystem or prefix state.

The producer exports the same bounded proof/type DAG with its reported integer
raw heartbeat count. The parent rejects wrong methods, malformed/nonfinite,
Boolean, negative or over-63-bit counters. Zero is valid data, not a default.
The fresh checker receives neither candidate source nor the measured counter;
it cannot authenticate either. Every observation retains
`metric_integrity_established=false`, `candidate_source_verified=false` and
`counter_authority="untrusted_producer"`, even when proof data checks. Parent-side
`parent_stage_wall_ms` records actual stage/preflight/cleanup elapsed time,
separately from heartbeats; fixture wall time is not Lean or model latency.

A comparison freezes both sources, a seeded schedule, two process-order strata,
2–5 repetitions **per order**, the noise floor and context before work. Orders
describe separate-process launch order, never branches in a shared process.
With two arms, two orders and two repetitions there are eight observations;
each uses a producer and checker, so the entire **16-unit** budget is reserved
before the first launch. Partial capacity (including 0 or 15) runs nothing.
Reservations are single-owner integer tickets, consumed once; no retries, cached
measurements or refunds are allowed. On a failed sample the batch stops, retains
the failed observation and prior history, cancels unused tickets without refund,
and emits no comparison. A 64 MiB compact-report bound also stops the batch;
an oversized sample leaves its hash/status and full charge accounting, not a
manufactured successful record. Pretty-printed CLI output may occupy more bytes.
Top-level counters are this batch's deltas, with separate lifetime totals;
nested observation counters retain the adapter's cumulative accounting. Do not
sum nested cumulative counters as if they were additional charges.

`OBSERVED` (or `FIXTURE_OBSERVED`) means the fixed batch completed, **not** that
source/cost integrity was established or a refactor was admitted. The report
retains raw arrays and uses the existing separated-range/noise-floor rule for
descriptive comparison. `both_lower_in_observations` also requires fewer source
tokens, but remains non-authoritative; `promotion_eligible` is always false.
Identity, ties, slower candidates and overlapping ranges cannot produce that
descriptive flag. `INCOMPLETE` retains the underlying sample failure; setup
errors/unavailability/timeouts and budget exhaustion remain distinct outcomes.

Example, with explicit existing local Docker/toolchain inputs:

```bash
python -m jevops.arena_replay --smoke --cold --elan-home /path/to/elan \
  --tag v4.26.0 --docker-socket "$ARENA_DOCKER_SOCKET" \
  --docker-image-id "$ARENA_DOCKER_IMAGE" --max-processes 16 \
  --repetitions 2 --seed 17 --noise-floor-raw 0 --output /path/to/new-cold-report.json
```

This smoke is not a benchmark candidate search, all-pin confirmation or an
incumbent selector. The CLI still refuses to overwrite evidence. A zero exit
code indicates report emission only. The reused `challenge.heartbeat_method`
describes the legacy context guard; `plan.measurement` and each observation's
`measurement` identify the **new** cold protocol. Never mix these arrays with
legacy paired measurements or published Arena heartbeat denominators.

The live warmth canary deliberately installs trusted test tactics that cache a
marker in the worker's private `/tmp`. A candidate appears cheaper after the
reference warms that state in the old paired worker, but becomes more expensive
when measured in a fresh producer. This tests a concrete cross-branch artifact,
not immunity to arbitrary counter resets, hidden work or forged producer data.
The work is repeated Lean tactic elaboration, not synthetic counter increments.
Native cases inherit the `live_profile` fresh-fixture protection: ordinary seal
reuse never substitutes for live measurements. Pure offline protocol tests may
reuse seals during development; use `--test-seal=refresh` for fresh evidence.

## Checked export-size guard — partial ticket 1d

`ArenaTermReplay(..., cold_measurement=True, export_size_guard=True)` adds an
opt-in structural non-growth requirement to `cold_comparison`. The CLI spelling
is `--cold --export-size-guard`; omitting `--cold` is an error before toolchain
or Docker access. This extends the existing adapter/codec, not the verifier's
proof authority or the selector's official cost formula.

After each fresh checker succeeds, the parent computes `checked_export_size`
from that exact export using `expr_dag.root_summaries`. Producer/checker-supplied
size fields are rejected. The export hash must remain unchanged across checking.
An unsuccessful checker yields no checked size, and an incomplete batch yields
no size comparison. Injected runners remain explicitly `offline_fixture` with
`proof_data_checked=false`; their numbers are protocol fixtures, not Lean results.

The versioned policy is `nonexpanding-checked-proof-and-type/v1`. It binds into
the immutable environment and cold plan; removing/changing the guard mid-epoch
invalidates the operation. For each process-order stratum, it requires every
candidate sample to be no larger than every control sample on **all** of:

- Unique expression nodes, expanded expression nodes and expression depth,
  separately for proof and type roots.
- Total unique expression nodes and universe-level nodes in the shared export.
- Canonical serialized export bytes, so larger literals/metadata cannot hide
  behind unchanged node counts. This is not compressed size or a new Arena score.

Tree counts are computed over the bounded DAG without materializing its expanded
tree. A heavily shared term can have unchanged unique-node count yet a larger
expanded tree; this also fails the guard. Metadata is counted, not discarded for
size comparisons. Equal or smaller sizes pass only this structural condition.

The report retains per-order min/max ranges and every violating metric. Growth
returns `GUARD_REJECTED` / `checked_export_size_growth`, retaining all observations
and full reservation/attempt accounting. This is a failed refactor cost guard,
**not a disproof or invalidity of the theorem**. No retry, refund, best-repeat
selection or weighted compensation is used. The existing descriptive
`comparison.both_lower_in_observations` still reports only source tokens and
producer counters: it can be true while the batch is `GUARD_REJECTED`. Never use
that isolated flag as admission. `evaluate` collects one size record; only a
complete `cold_comparison` applies the control-relative guard.

This checks **exported data only**: it does not unfold constant bodies, measure
universe-level tree expansion, audit import/parse/elaboration/export costs or
authenticate which source was executed. Even when combined with
`--explicit-source`, the existing source-execution, metric-integrity, promotion
and training flags remain false. There is no automatic strict-selector wiring,
incumbent arm or all-pin promotion here; full phase-1 acceptance is still open.

To add this guard to the existing non-Arena cold smoke, append
`--export-size-guard` to its command above (and optionally `--explicit-source`).
The same 16-unit minimum applies. The two new opt-in native canaries exercise
explicit `@h` versus the larger `(@f (@f @h))` on Lean 4.26/4.34; their status
must be reported from an actual opted-in run, never inferred from offline tests.

Validation for this increment (2026-09-23):

```bash
env -u JEVOPS_ARENA_DOCKER_TESTS -u JEVOPS_ARENA_NATIVE_TESTS \
  python -m pytest -q --test-seal=refresh \
  tests/test_arena_replay.py tests/test_arena_source.py tests/test_expr_dag.py \
  tests/test_proof_metrics.py tests/test_arena_pareto.py tests/test_arena_report_audit.py
# 386 passed, 27 skipped in 50.19s; zero reused, 369 fresh passes sealed.
```

This includes fresh offline cases for equal/smaller exports; proof/type growth;
expanded-tree-only and byte-payload-only growth; a late-repeat regression;
forged sizes, checker failure and export mutation; policy/context mutation;
zero/partial budgets and CLI validation. Existing source/replay, codec, metric,
selector and saved-report regressions also passed. Fixtures never acquire native
authority. The two new live canaries were **not run**: nonblocking acquisition
of the existing single-build lock failed, so no concurrent native experiment was
started. This run establishes offline behavior, not fresh Lean compatibility,
an optimization improvement, a full repository pass or a completed phase-1 gate.
The subsequent [native follow-up](#native-export-size-guard-validation-2026-09-23)
ran both canaries and non-growing controls once the lock became available.

## Observed validation, 2026-09-23

The complete replay suite passed **37 tests in 79.29 seconds**: 27 offline tests
and all 10 opted-in Docker/Lean 4.26 cases. The live cases cover valid data;
kernel-invalid terms; wrong target/type/universes; missing constants; `sorry`
axiom rejection; scoped and polymorphic proofs; and the explicit source-
substitution limitation. A failed initial fixture using `scoped` as a theorem
name also failed the existing native driver; the namespace regression now uses
the ordinary name `sample`. No checker gate was weakened to accommodate it.

Exact live command:

```bash
flock -n /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/single-build.lock \
  env TMPDIR=/tmp JEVOPS_ARENA_DOCKER_TESTS=1 \
  JEVOPS_ARENA_DOCKER_SOCKET=/run/user/1000/docker.sock \
  JEVOPS_ARENA_DOCKER_IMAGE=sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517 \
  ELAN_HOME=/home/barberb/.elan python -m pytest -q -x --test-seal=off tests/test_arena_replay.py
```

Separate CLI smokes also returned `PROOF_DATA_CHECKED` on
[Lean 4.26](papers/completion/lean_refactor_arena/evidence/native-term-replay-smoke-v4.26.0-2026-09-23.json)
and [Lean 4.34](papers/completion/lean_refactor_arena/evidence/native-term-replay-smoke-v4.34.0-2026-09-23.json),
with two process attempts each and source verification still explicitly false.
The same locked command below was run for each tag, sequentially (replace
`v4.26.0` in **both** places by `v4.34.0` for the second report):

```bash
flock -n /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/single-build.lock \
  env TMPDIR=/tmp python -m jevops.arena_replay --smoke \
  --elan-home /home/barberb/.elan --tag v4.26.0 --max-processes 2 \
  --docker-socket /run/user/1000/docker.sock \
  --docker-image-id sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517 \
  --output papers/completion/lean_refactor_arena/evidence/native-term-replay-smoke-v4.26.0-2026-09-23.json
```

The broader offline regression passed **666 tests, 124 skipped, in 4.90 seconds**:

```bash
env -u JEVOPS_ARENA_DOCKER_TESTS -u JEVOPS_ARENA_NATIVE_TESTS \
  python -m pytest -q -rs --test-seal=off \
  tests/test_arena_replay.py tests/test_arena.py tests/test_arena_isolation.py \
  tests/test_arena_lean.py tests/test_arena_projects.py tests/test_arena_module_audit.py \
  tests/test_arena_trial.py tests/test_arena_pareto.py tests/test_arena_report_audit.py \
  tests/test_arena_snapshot.py tests/test_arena_compositions.py tests/test_arena_rules.py \
  tests/test_arena_prepare.py tests/test_arena_recovery_evidence.py \
  tests/test_arena_providers.py tests/test_premise_search.py
```

Those skips were opt-in native integrations; the counts overlap with the replay
suite and are not additive unique coverage. No complete repository run or full
prepared-corpus replay is claimed. No owned check containers remained afterward.
There were no downloads, dependency builds, live model calls, changes to shared
cache permissions or production proof updates. Both smoke reports are integration
evidence only, not a benchmark score or newly discovered optimization.

### Frozen-source confirmation

A post-run check found that another workstream changed `jevops/lean.py` after
the two initial smoke reports were emitted. Their recorded identities remain
historical evidence, not evidence for later workspace bytes. A fresh read-only
snapshot then captured 115 files (3,066,943 bytes) and supplied all Python/Lean
source for a separate confirmation. The concurrent edits were preserved.

Snapshot creation command:

```bash
python -m jevops.arena_snapshot create \
  --repo /home/barberb/lift_coding/JevOps \
  --output-dir /tmp/jevops-replay-confirm-MxKIC2/source \
  --include jevops --include tests/test_arena_replay.py \
  --include conftest.py --include pytest.ini --include pyproject.toml
```

From that snapshot directory, the following passed **27 tests, with 10 opt-in
native cases skipped, in 0.14 seconds**:

```bash
env -u JEVOPS_ARENA_DOCKER_TESTS -u JEVOPS_ARENA_NATIVE_TESTS \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/jevops-replay-confirm-MxKIC2/source TMPDIR=/tmp \
  python -m pytest -q -p no:cacheprovider --test-seal=off tests/test_arena_replay.py
```

The locked CLI command above was also rerun from that directory, with the same
`PYTHONDONTWRITEBYTECODE`, `PYTHONPATH` and `TMPDIR` settings, sequentially for
each tag. Its absolute output paths were
[frozen Lean 4.26 report](papers/completion/lean_refactor_arena/evidence/native-term-replay-frozen-v4.26.0-2026-09-23.json)
and
[frozen Lean 4.34 report](papers/completion/lean_refactor_arena/evidence/native-term-replay-frozen-v4.34.0-2026-09-23.json).
Both returned `PROOF_DATA_CHECKED`, two process attempts, and
`candidate_source_verified=false`. Both reports' `replay_code_identity` values
matched the imported frozen adapter's recomputed identity:
`1bcddafc8d79f8795a08bbc72970ca93988e29a1f049b173b93f4a74cfedde46`.
Boundary identities include absolute source paths, so a relocated snapshot is a
different context even when file contents match.

After all confirmation runs, this verification returned `UNCHANGED`:

```bash
env PYTHONDONTWRITEBYTECODE=1 \
  python /tmp/jevops-replay-confirm-MxKIC2/source/jevops/arena_snapshot.py verify \
  --root /tmp/jevops-replay-confirm-MxKIC2/source \
  --manifest-sha256 8dc343e040ae9f96790e69bc13547f33562864cc24ca5dc811e53e749391a14b
```

The snapshot content-root SHA-256 is
`15779e3ed043ac39b8c04777640d11e3c981de5e829a1759de793ff8ab8ddae2`.
The source copy is temporary local evidence, not a committed archive or an OS
sandbox; installed Python and Lean dependencies were not copied. Reports are
retained in the repository. No owned checker containers remained after this
confirmation. The complete live suite and broader offline suite were not
repeated against this snapshot; their earlier results must not be relabeled as
frozen-source results.

## Cold extension validation, 2026-09-23

Files changed for this increment: `jevops/arena_replay.py` adds the explicit mode,
batch reservations and comparison; `jevops/lean/ArenaReplay.lean` exposes the
single-branch counter; `tests/test_arena_replay.py` adds protocol and live warmth
regressions. README and the token/heartbeat safety plan link the feature without
claiming closure of the source/cost trust gates. No new framework or dependency
was added. A falsy injected callable is also now consistently labeled a fixture,
not mistaken for a native runner in the report's status or evidence mode.

The final read-only source bundle was created with:

```bash
python -m jevops.arena_snapshot create \
  --repo /home/barberb/lift_coding/JevOps \
  --output-dir /tmp/jevops-cold-check-MUaD4P/source-v4 \
  --include jevops --include tests/test_arena_replay.py \
  --include conftest.py --include pytest.ini --include pyproject.toml
```

From that directory, this command passed **80 tests in 111.55 seconds**, including
all **12 live Docker/Lean 4.26 cases** and 68 offline cases. `refresh` executed
every body; 62 fresh passes were eligible for sealing. The cache directory is
outside the read-only bundle; no seal provider or native opt-out was disabled.

```bash
flock -n /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/single-build.lock \
  env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/jevops-cold-check-MUaD4P/source-v4 \
  TMPDIR=/tmp JEVOPS_ARENA_DOCKER_TESTS=1 \
  JEVOPS_ARENA_DOCKER_SOCKET=/run/user/1000/docker.sock \
  JEVOPS_ARENA_DOCKER_IMAGE=sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517 \
  ELAN_HOME=/home/barberb/.elan python -m pytest -q -x --test-seal=refresh \
  -o cache_dir=/tmp/jevops-cold-check-MUaD4P/pytest-cache-v4 tests/test_arena_replay.py
```

Cold CLI smokes then ran sequentially under the same lock and frozen Python
path. The command below was executed for `v4.26.0` and `v4.34.0`, substituting
the tag in both its argument and output filename:

```bash
flock -n /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/single-build.lock \
  env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/jevops-cold-check-MUaD4P/source-v4 \
  TMPDIR=/tmp python -m jevops.arena_replay --smoke --cold \
  --elan-home /home/barberb/.elan --tag v4.26.0 --max-processes 16 \
  --repetitions 2 --seed 17 --noise-floor-raw 0 \
  --docker-socket /run/user/1000/docker.sock \
  --docker-image-id sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517 \
  --output /home/barberb/lift_coding/JevOps/papers/completion/lean_refactor_arena/evidence/native-cold-replay-smoke-v4.26.0-2026-09-23.json
```

Both returned `OBSERVED`, with eight proof-data-checked observations, 16 reserved
units and 16 stage attempts. The retained reports are
[Lean 4.26](papers/completion/lean_refactor_arena/evidence/native-cold-replay-smoke-v4.26.0-2026-09-23.json)
and [Lean 4.34](papers/completion/lean_refactor_arena/evidence/native-cold-replay-smoke-v4.34.0-2026-09-23.json).
Each of the four observations per arm had the following counts:

| Pin | Reference → candidate proof tokens | Producer-reported raw heartbeats |
| --- | --- | --- |
| v4.26.0 | 8 → 3 | 6,525 → 3,975 |
| v4.34.0 | 8 → 3 | 7,467 → 4,535 |

These are tiny non-Arena integration controls, not new optimization discoveries,
an official score, calibrated noise estimates or security-certified savings.
Every report retains false source/metric/promotion eligibility flags. The replay
identity in both reports matched the frozen implementation:
`e16a05b2a7f74a212b2d99e05023a4b92de3d6b75e3ade30e1673692945186e9`.

The broader current-worktree offline regression also passed **388 tests, 103
skipped in 17.03 seconds**, with 370 fresh passes sealed and zero reused:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=refresh \
  tests/test_arena_replay.py tests/test_arena_pareto.py tests/test_arena_trial.py \
  tests/test_arena_report_audit.py tests/test_arena_isolation.py tests/test_arena_lean.py
```

All 103 skips were explicitly opt-in native integrations. Counts overlap with
the replay suite and are not additive. `--test-seal=status` on the replay file
with `-k live` returned the expected exit 1: all 12 live cases required fresh
execution through `live_profile`, with 68 other cases deselected.

Initial live attempts are **not** passing evidence. They caught an effectful
measurement-field read in ordinary replay mode; moving that read inside the
explicit branch fixed the regression without changing the gate. The first warmth
fixture used a same-module initialized reference that Lean could not evaluate;
the next string-work fixture did not create the expected heartbeat separation.
The final fixture uses a private scratch marker and repeated Lean tactic
elaboration. Its assertions were not weakened: paired candidate cost is lower,
fresh candidate cost is higher, and both exported proof terms still check.

After all native runs, this command returned `UNCHANGED`:

```bash
env PYTHONDONTWRITEBYTECODE=1 \
  python /tmp/jevops-cold-check-MUaD4P/source-v4/jevops/arena_snapshot.py verify \
  --root /tmp/jevops-cold-check-MUaD4P/source-v4 \
  --manifest-sha256 b2fcc6d64971e821b4780ddafe7b193ff2473208637c4a3b46bf14571afc526c
```

It contains 115 files, 3,101,862 bytes, with content-root SHA-256
`1e17bd6d4ad9fd8ada459a1072919b5612c53958734d9d84293da458a9a1c898`.
The three implementation/test files also matched their worktree counterparts
byte-for-byte. This temporary source bundle is not a permanent archive or a copy
of the installed dependencies. No owned verifier containers remained. There were
no downloads, dependency builds, model calls, production edits, commits or pushes;
the complete repository suite and prepared Arena corpus were not run.

## Explicit-term gate validation, 2026-09-23

This continuation adds `jevops/arena_source.py` (bounded source plans and DAG
matching) and `tests/test_arena_source.py`, integrates the opt-in policy/CLI with
`jevops/arena_replay.py`, and extends `tests/test_arena_replay.py`. The existing
Lean checker, isolation settings and admission restrictions were not loosened.
README and the safety plan link to the new boundary and its limitations.

Final fresh offline regression command, from the working checkout:

```bash
env -u JEVOPS_ARENA_DOCKER_TESTS -u JEVOPS_ARENA_NATIVE_TESTS \
  python -m pytest -q --test-seal=refresh \
  tests/test_arena_source.py tests/test_arena_replay.py \
  tests/test_arena_pareto.py tests/test_arena_trial.py \
  tests/test_arena_report_audit.py tests/test_arena_isolation.py tests/test_arena_lean.py
```

Observed: **473 passed, 114 skipped, 21.28 seconds**, zero reused seals. These
are focused suites, not the complete repository. Other agents were updating
the checkout; native validation therefore used the read-only source snapshot
`/tmp/jevops-source-check-37COp9/source-v3` (119 files, 3,174,763 bytes).
Its manifest SHA-256 is
`c77629faf62c523bd65fd80d6d4766a4c1538d9470665870b57af1c52253036e`,
and content-root SHA-256 is
`8fa71cc6225515865a750de6efef23c6e265ba83cb09cf55238323a0c5bccee2`.
The snapshot was created with:

```bash
python -m jevops.arena_snapshot create --repo /home/barberb/lift_coding/JevOps \
  --output-dir /tmp/jevops-source-check-37COp9/source-v3 \
  --include jevops --include tests/test_arena_replay.py --include tests/test_arena_source.py \
  --include conftest.py --include pytest.ini --include pyproject.toml
```

From that snapshot directory, the following full test/CLI sequence ran under
one exclusive lock. Earlier lock contention caused no launch and was not bypassed:

```bash
flock -n /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/single-build.lock \
  env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/jevops-source-check-37COp9/source-v3 \
  TMPDIR=/tmp JEVOPS_ARENA_DOCKER_TESTS=1 \
  JEVOPS_ARENA_DOCKER_SOCKET=/run/user/1000/docker.sock \
  JEVOPS_ARENA_DOCKER_IMAGE=sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517 \
  ELAN_HOME=/home/barberb/.elan bash -c '
python -m pytest -q -x --test-seal=refresh \
  -o cache_dir=/tmp/jevops-source-check-37COp9/pytest-cache-v3 \
  tests/test_arena_source.py tests/test_arena_replay.py || exit $?
for arena_tag in v4.26.0 v4.34.0; do
  python -m jevops.arena_replay --smoke --explicit-source --cold \
    --elan-home /home/barberb/.elan --tag "$arena_tag" --max-processes 16 \
    --repetitions 2 --seed 17 --noise-floor-raw 0 \
    --docker-socket /run/user/1000/docker.sock \
    --docker-image-id sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517 \
    --output "/home/barberb/lift_coding/JevOps/papers/completion/lean_refactor_arena/evidence/native-explicit-cold-replay-smoke-$arena_tag-2026-09-23.json" || exit $?
done
'
```

The full frozen suite returned **163 passed in 193.35 seconds**: 140 offline
tests and 23 explicitly opted-in integration cases (one checks refusal before
launch). There were zero reused seals, with 134 fresh passes sealed. A preceding
targeted run of `tests/test_arena_replay.py -k live_explicit`, under the same
profile and final snapshot, returned **11 passed, 96 deselected in 80.26 seconds**.
The status-only command `python -m pytest --test-seal=status -q
tests/test_arena_replay.py -k live` confirmed every one of the 23 live cases stays
unsealed because of `live_profile`; its exit 1 means unsealed, not a test failure.

The initial native attempt is not passing evidence: its conjunction case exposed
implicit-argument insertion across nested partial application groups. It stopped
with **1 failed, 155 passed**. The final grammar uses one explicit application
spine per group and rejects nested application heads. Offline tests now cover
left associativity and the expanded AST's node/depth limits; both Lean versions
pass the unchanged conjunction proof-structure assertion. No kernel or axiom
check was relaxed to accommodate that failure.

Both final CLI reports returned `OBSERVED` with eight structurally matched,
kernel-checked observations and exactly **16 reserved / 16 attempted** stage
units per report:

| Installed pin / saved report | Tokens, control → candidate | Producer-reported raw heartbeats, control → candidate | Strict dual reduction? |
| --- | --- | --- | --- |
| [4.26.0](papers/completion/lean_refactor_arena/evidence/native-explicit-cold-replay-smoke-v4.26.0-2026-09-23.json) | 4 → 4 | 4065 → 3981 | No |
| [4.34.0](papers/completion/lean_refactor_arena/evidence/native-explicit-cold-replay-smoke-v4.34.0-2026-09-23.json) | 4 → 4 | 4842 → 4549 | No |

Each arm's raw values were identical across both repetitions and both process
orders in these runs. These are **neutral source-token controls**, not an Arena
optimization or authenticated timing result. Both reports keep the metric and
source-execution authority flags false, `promotion_eligible=false`, and a null
official score. Their replay-code identity is
`4c88694adb4a8969b2d2ea2ca8de6548544de2cbc621d5b5716f356cc776e1e2`.
The separate source/type data remain fully inspectable in each report.

After the native runs, snapshot verification returned `UNCHANGED`:

```bash
python -m jevops.arena_snapshot verify --root /tmp/jevops-source-check-37COp9/source-v3 \
  --manifest-sha256 c77629faf62c523bd65fd80d6d4766a4c1538d9470665870b57af1c52253036e
```

The four implementation/test files matched the working copies byte-for-byte.
No owned verifier containers remained. No downloads, dependency builds, model
calls, corpus trials, production promotion, commits or pushes were performed.
Temporary source bundles are not a permanent archive or dependency mirror.

## Native export-size guard validation, 2026-09-23

The previously unrun growth canaries now pass on installed Lean **4.26.0 and
4.34.0**. No implementation or assertion was changed to obtain these results.
Each canary checks `by exact @h` against `by exact (@f (@f @h))`, with explicit
parameters `(f : True -> True) (h : True)`. All eight proof-data observations
pass fresh kernel replay, but the larger candidate returns
`GUARD_REJECTED` / `checked_export_size_growth`. This rejects a structural-cost
regression, not the truth of `True`.

The native and regression commands below ran from
`/tmp/jevops-export-size-live-mobJEK/source`, a read-only source copy containing
121 files / 3,268,074 bytes. It was created with:

```bash
python -m jevops.arena_snapshot create --repo /home/barberb/lift_coding/JevOps \
  --output-dir /tmp/jevops-export-size-live-mobJEK/source \
  --include jevops --include tests/test_arena_replay.py --include tests/test_arena_source.py \
  --include conftest.py --include pytest.ini --include pyproject.toml
```

Its externally retained manifest SHA-256 is
`a73eeae9fa4a8a39f135b7b7c23ad405880ac63cc6c8d60c7c7f2596f5a5fc72`;
the content-root SHA-256 is
`72636393bb73215aad04a839bfa045cb216437cf0f80f8c6a088f492f177d0e3`.
These are content identities, not proofs or an installed-dependency snapshot.

The native canary command was:

```bash
flock -n /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/single-build.lock \
  env PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/tmp/jevops-export-size-live-mobJEK/source TMPDIR=/tmp \
  JEVOPS_ARENA_DOCKER_TESTS=1 \
  JEVOPS_ARENA_DOCKER_SOCKET=/run/user/1000/docker.sock \
  JEVOPS_ARENA_DOCKER_IMAGE=sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517 \
  ELAN_HOME=/home/barberb/.elan \
  python -m pytest -q -x --test-seal=refresh \
  -o cache_dir=/tmp/jevops-export-size-live-mobJEK/cache \
  --basetemp=/tmp/jevops-export-size-live-mobJEK/pytest-tmp \
  --junitxml=/tmp/jevops-export-size-live-mobJEK/canaries.xml \
  tests/test_arena_replay.py -k live_size_guard
# 2 passed, 130 deselected in 106.26s; zero reused seals.
```

Each canary asserted exactly 16 reserved / 16 attempted process units. The
`live_profile` fixture keeps these integration cases unsealed. The broader
offline regression command used the same frozen source, without native opt-in:

```bash
env -u JEVOPS_ARENA_DOCKER_TESTS -u JEVOPS_ARENA_NATIVE_TESTS \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/jevops-export-size-live-mobJEK/source \
  python -m pytest -q --test-seal=refresh \
  -o cache_dir=/tmp/jevops-export-size-live-mobJEK/offline-cache \
  --basetemp=/tmp/jevops-export-size-live-mobJEK/offline-tmp \
  tests/test_arena_replay.py tests/test_arena_source.py
# 163 passed, 25 skipped in 2.70s; zero reused, 157 fresh passes sealed.
```

Non-growing controls were then run sequentially under the same exclusive lock,
with a new 16-unit budget per version:

```bash
flock -n /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/single-build.lock \
  env PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/tmp/jevops-export-size-live-mobJEK/source TMPDIR=/tmp bash -c '
for arena_tag in v4.26.0 v4.34.0; do
  python -m jevops.arena_replay --smoke --explicit-source --cold --export-size-guard \
    --elan-home /home/barberb/.elan --tag "$arena_tag" --max-processes 16 \
    --repetitions 2 --seed 17 --noise-floor-raw 0 \
    --docker-socket /run/user/1000/docker.sock \
    --docker-image-id sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517 \
    --output "/home/barberb/lift_coding/JevOps/papers/completion/lean_refactor_arena/evidence/native-size-guard-cold-smoke-$arena_tag-2026-09-23.json" || exit $?
done
'
```

Both reports returned `OBSERVED`, with eight fresh `PROOF_DATA_CHECKED` samples,
`EXPLICIT_TERM_STRUCTURE_CHECKED`, `nonregressing=true`, no size violations and
exactly 16 reserved / 16 attempted units. The CLI exit code only indicates report
emission; these fields and the non-authority flags were separately inspected.

| Installed pin / saved report | Tokens, control → candidate | Producer-reported raw heartbeats, control → candidate | Canonical export bytes, control → candidate | Strict dual reduction? |
| --- | --- | --- | --- | --- |
| [4.26.0](papers/completion/lean_refactor_arena/evidence/native-size-guard-cold-smoke-v4.26.0-2026-09-23.json) | 4 → 4 | 4065 → 3981 | 503 → 474 | No |
| [4.34.0](papers/completion/lean_refactor_arena/evidence/native-size-guard-cold-smoke-v4.34.0-2026-09-23.json) | 4 → 4 | 4842 → 4549 | 503 → 474 | No |

For both versions, both repetitions and both process orders, each arm's values
were identical. Proof unique/expanded nodes were 3/3 and depth 2; type
unique/expanded nodes were 2/3 and depth 2; the shared export contained four
expression nodes and zero level nodes. These sizes were equal between arms;
only canonical export bytes decreased. Source tokens stayed equal, so neither
control is a strict-dual improvement. The raw heartbeats remain unauthenticated
producer counters, not an independently established cost result.

Both reports use replay-code identity
`48053ea52052346941f29f59560cf5b44dd081c44ddcb2e976c818584e6446d6`.
Their file SHA-256 hashes are respectively
`9a424691f0cc5939f055188bd87e0777e614a8857cf5e718ed4c023fd7e0113c` and
`0f8eea2aa81a2f0b40ec05f147a8e77ba89cd7491fb4a239b79feaa8fe3d36a6`.
They retain `arena_problem=false`, null `official_score`, and false
`candidate_source_verified`, `source_execution_attested`,
`metric_integrity_established`, `promotion_eligible`, `promoted` and
`training_enabled`. Passing the size guard grants none of those authorities.

Post-run snapshot verification returned `UNCHANGED`:

```bash
env PYTHONDONTWRITEBYTECODE=1 \
  python /tmp/jevops-export-size-live-mobJEK/source/jevops/arena_snapshot.py verify \
  --root /tmp/jevops-export-size-live-mobJEK/source \
  --manifest-sha256 a73eeae9fa4a8a39f135b7b7c23ad405880ac63cc6c8d60c7c7f2596f5a5fc72
```

Sixteen relevant implementation, boundary, Lean-driver and test files also
matched their working copies byte-for-byte. No verifier-owned containers
remained. Total native usage was **64 reserved / 64 attempted stage units**:
32 for the two rejection canaries, 32 for the two control reports. There were
no downloads, dependency builds, model calls, corpus trials, production
promotion, commits or pushes. The 50 GB provisioning cap was not enlarged.
This establishes live compatibility of this partial safeguard on two pins, not
an Arena improvement, a full repository pass or completion of phase 1.
