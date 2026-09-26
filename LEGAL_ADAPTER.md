# Explicit legal adapter: declared source pins and per-run ownership

This is the second bounded implementation slice of
[the federal-law training plan](FEDERAL_LAW_TRAINING_PLAN.md), following the
[legal source lock](LEGAL_SOURCE_LOCK.md). It does not implement corpus-scale
training, qualify the native legal compiler, or establish legal fidelity.

`jevops.legal_adapter.PinnedLegalAdapter` wraps the existing legal session
interface. There is no new compiler, scheduler, dependency, or global adapter
registry. The wrapper never imports `ipfs_datasets_py`, changes `sys.path`, or
selects a workspace directory. The caller supplies:

- An absolute source root, a `SourceManifest`, and a separately approved manifest
  SHA-256 content hash.
- A session and its exact document-store object. Separate runs need separate
  sessions/documents; deliberately sharing a supplied object still shares state.
- A verifier callback, attestation writer and optional prompt builder. Missing
  dependencies never fall back to an ambient backend. The callbacks are trusted
  application dependencies, not model-provided tool arguments.

## Existing entry points

The following functions in `jevops.autoformal_tools` accept `adapter=...`:

| Entry point | Injected behavior |
| --- | --- |
| `dispatch` | Five legal tools call the supplied session; `lake_check` uses the supplied verifier; extraction remains local |
| `admit_roundtrip_rule` | Locks against the rendered expected rule, then uses the supplied verifier and writer |
| `admit_locked` | Reads obligations and marks dispositions on the supplied document store; verifies only source-locked edits |
| `run_leanstral` | Uses the supplied prompt builder and adapter for tool calls, candidate checks and the final check |

`adapter.open_document` also guards the caller-owned session's document intake.
Only the existing five legal read/compile operations are available to model tool
dispatch. Their argument names are allowlisted; identifiers must be nonempty
UTF-8 strings of at most 1,024 bytes without control characters. Flags such as
`theorem_ok` cannot select a backend or authorize admission.

Omitting `adapter` preserves the legacy loading/calling paths. In particular,
`run_neighbor_objective` and direct `lake_check` are **not migrated** by this
slice. Do not describe an arbitrary existing campaign as isolated just because
this optional interface exists. The injected `lake_check` tool accepts only the
restricted legal source profile; general Arena Lean editing is unchanged.

Leanstral's existing local-model selection, request bounds and endpoint policy
are unchanged. `run_leanstral` still performs a real model request when invoked
normally. Its tests replace that request with a clearly labeled fixture. Its
successful compilation result is not source-bound legal admission: use an
admission function with a trusted expected rule/obligation for that boundary.

## Source identity and failure behavior

The versioned manifest records `implementation_id` and a sorted, unique tuple of
relative paths, exact lengths and SHA-256 content hashes. `as_dict` / `from_dict`
support persistence. Its digest is over sorted-key, compact ASCII JSON. Only the
declared schema/types are accepted; Boolean/float file sizes, unknown fields,
duplicate paths, traversal and unsupported schema versions fail. There are at
most 128 files, 16 MiB per file and 64 MiB total. A declared zero-byte file must
remain empty. These bounds apply to source artifacts, not model or corpus data.

Enrollment is explicit:

```python
manifest = SourceManifest.capture(
    reviewed_root,
    reviewed_relative_paths,  # tuple; explicit caller-reviewed artifact set
    implementation_id="your-qualified-legal-backend/revision",
)
```

Review and retain `manifest.as_dict()` and its `content_sha256` independently.
Capturing the current tree and automatically accepting its new digest on every
run is **not version pinning**. Names/labels alone are not identities. File
contents can be copied to a different root without changing the manifest hash.
Adding a dependency requires reviewing and enrolling a new manifest, not
silently extending an active one.

For run composition, the caller supplies already constructed dependencies:

```python
from jevops.legal_adapter import PinnedLegalAdapter, SourceManifest
from jevops.autoformal_tools import dispatch, admit_roundtrip_rule

manifest = SourceManifest.from_dict(approved_manifest_record)
adapter = PinnedLegalAdapter(
    root=source_root,
    manifest=manifest,
    expected_sha256=approved_manifest_sha256,
    session=owned_session,
    documents=owned_documents,  # owned_session.documents must be this object
    verifier=qualified_verifier,
    attestation_writer=owned_attestation_writer,
    prompt_builder=explicit_prompt_builder,
)
try:
    compiled = dispatch("compile_clause", {
        "document_id": document_id, "clause_id": clause_id,
    }, adapter=adapter)
    # Round-trip classification/review remains the caller's existing workflow.
    result = admit_roundtrip_rule(
        trusted_roundtrip_row, candidate_reply,
        repository=owned_repository, adapter=adapter,
    )
finally:
    adapter.close()
```

The sibling's inspected `AutoformalSession(documents=...)` interface matches
this wrapper. Bootstrap/imports belong to the application. That backend still
has internal imports/tree checks, and importing it may construct its own global
session; this wrapper neither uses nor eliminates those module side effects.
No qualified native source manifest ships in this slice. The application must
freeze its implementation, validate imports and include relevant compiler,
renderer, prompt, configuration and verifier artifacts before native trials.

The constructor checks the supplied digest and current files. Every backend
call then hashes the entire declared set before and after execution, also
checking the document-store binding. Symlink leaves/ancestors, nonregular files,
missing files, size/hash drift and detected changes during reads fail. This is
bounded **global work over the manifest**, not a sparse/incremental source check;
include its I/O cost in future end-to-end measurements.

Drift, malformed verifier/writer output, or a callback exception raises
`AdapterError` and poisons the adapter. Restoring old file bytes does not revive
it. A new run must explicitly bind new dependencies after recovery. A missing
verifier returns `lake_ok=false, error=verifier_unavailable`; a semantic rejection
returns the verifier's false result; a timeout raises an infrastructure error
with its original cause. None is positive evidence. A writer must return an
actual Boolean `indexed`, and the verifier an actual Boolean `lake_ok` plus a
string `error`; truthy strings and legacy proof flags are rejected.

Calls belong to the constructing process/thread, with reentrant calls refused.
`close()` is idempotent and disables calls without deleting/closing caller-owned
objects. This is not a cross-process lock or concurrent worker implementation.

## Trust boundary and remaining limits

The source lock checks helper/target preservation. The injected verifier checks
proofs under its own declared policy. `source_adapter` in returned admission or
generation results records the manifest identity with
`verification_performed=false`: it is provenance, not a proof, calibrated model
score, standards CID or complete toolchain-bound receipt. The attestation
writer's existing payload contract is unchanged; this slice does not guarantee
durable storage of the additional provenance.

Pre/post hashing does not attest loaded Python bytecode, discover omitted
dependencies, pin executable/toolchain selection, or prevent a hostile
mutate-and-restore race between checks. It is not an OS sandbox. Expected helper
definitions and callbacks remain trusted. A false-positive mock verifier can
produce a fixture success; that is not evidence about real Lean or legal prose.

The wrapper cannot roll back an already executed callback. If a compile, mark or
writer mutates its own state before post-call drift is detected, the caller must
discard/recover that poisoned session or use an application-owned transaction.
No automatic retry, receipt replay, win deduplication or publication is added.
An unchanged file set also does not freeze document contents or external DB
state; source/version/obligation-bound durable receipts remain a separate gate.

## Offline verification

`tests/test_legal_adapter.py` uses only temporary declared text artifacts, owned
fixture sessions, mock verifiers/writers and a mock model response. It forbids
ambient loaders/stores, real Lake and model requests. It exercises two interleaved
sessions with identical document IDs, manifest round-tripping and limits, wrong
pins, pre/post-call drift, malformed outputs, command rejection, unavailable and
transient infrastructure, thread ownership/reentrancy and the entire two-turn
Leanstral tool/final-source path. A separate regression explicitly demonstrates
that post-call drift does not roll back a backend's prior mutation.

Run the expanded regression without native integrations:

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
  JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
  python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-legal-adapter-tests/cache \
  tests/test_legal_adapter.py tests/test_statement_lock.py \
  tests/test_legal_source_admission.py tests/test_autoformal_tools.py \
  tests/test_proof_ca.py tests/test_duckdb_ingest.py \
  tests/test_skillcenter_corpus.py tests/test_muse.py \
  tests/test_legal_document.py::test_a_deadline_rule_is_not_rendered_or_stored \
  tests/test_legal_document.py::test_import_and_a_changed_numeral_never_reach_lake \
  -k 'not legal_autoformal_prompt_does_not_bake_in_the_text' -q
```

The excluded prompt test requires the sibling module; other legacy document
tests include unguarded native Lake work and are deliberately not selected.
This command is a regression subset, not the full repository suite. No live
compiler/model, corpus download, training job, daemon or Hub upload is needed.
