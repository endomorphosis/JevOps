# Stable-snapshot local-edit pilot — September 23, 2026

This follows the [output-budget experiment](REFACTOR_OUTPUT_BUDGET_EXPERIMENT.md),
whose native phase was invalidated by concurrent edits. It uses the existing
`arena_snapshot` utility and native verifier, not a separate agent framework.
The task remains the previously studied public warm-up problem
`Core.InitsUpdatesComm`; this is not held-out evaluation or an official score.

## Generation results

| Treatment | Intake accepted | Other outcomes | Output tokens used |
| --- | --- | --- | ---: |
| Whole tactic body | 3/4 | One output-limit truncation | 2,700 |
| One source-bound deletion | 0/4 | Four contract mismatches | 188 |

All eight calls returned usage metadata: **22,756 prompt tokens and 2,888
output tokens**, with summed request wall time **168.7269 seconds**. The
server again reported `leanstral_local`, the Leanstral GGUF filename, and an
8,192-token per-slot context allocation; these are serving claims, not
independent model/weight attestation. No API or electricity cost was measured.

The span outputs contained a tool-call-shaped text wrapper, a Markdown fence,
a trailing assistant marker, or an object instead of the required two-integer
array. All were rejected unchanged: no tool was invoked, no wrapper was
silently removed, and no proposed deletion was executed. Three replies
mentioned body lines 8–14, but those numbers do not authorize an edit when the
enclosing contract fails. The low token use therefore is **not** an efficiency
win: this arm produced no admissible proposal.

The whole-body drafts contain 224, 240 and 223 local tokens against the
224-token reference. Draft 0 matches the reference body after removing a
uniform indentation offset; that comparison is an offline observation only,
not a mutation applied before verification. It is a neutral reproduction,
not a new refactoring. Draft 1 has inconsistent first-line indentation and
substantive changes; draft 2 changes the state used in an update obligation.
The shorter unverified length of draft 2 is not a score.

## Native results

The validity screen completed with **eight fresh native requests** and no
infrastructure or dependency-drift errors. All three reference controls passed.
Draft 0 verified on Lean 4.26.0, 4.27.0 and 4.29.1, preserving the target type
and allowed axiom set. Draft 1 was rejected on 4.26.0 for layout/unsolved goals;
draft 2 was rejected for a state mismatch in `updatedStateUpdate` and remaining
goals. Their four later-version checks were not run under the precommitted
fail-fast rule. Summed verification-request wall time was **116.8192 seconds**,
excluding initial context binding and fingerprint setup.

Draft 0 has the same 224-token size as the reference. Its scaled heartbeat
counts were also equal to both the controls and reference branches: 4,689,
4,657 and 4,227 respectively. Raw counters remain in the receipts; tiny raw
differences in this reference-first validity screen are not a performance claim.
No candidate qualified for the separate order-balanced performance confirmation.
Result: **one all-version-valid neutral reproduction, zero verified refactoring
improvements**. No training, performance selection or promotion occurred.

The source snapshot was unchanged after generation, native verification and
the subsequent offline harness self-check. This addresses the concurrent-code
drift observed in the previous experiment; it does not freeze every host
dependency forever or establish sandbox security.

The [evidence archive](papers/completion/lean_refactor_arena/evidence/prompt-local-edits-2026-09-23/)
contains the plan, responses, sources, receipts and snapshot manifest, with a
[machine-readable summary](papers/completion/lean_refactor_arena/evidence/prompt-local-edits-2026-09-23/summary.json).
The complete read-only source copy remains at the private location below;
the archived manifest alone does not contain those source files.

## Stable execution inputs

The independent source copy contains 219 files / 4,654,778 bytes: the JevOps
package, Lean driver, harness, frozen corpus, experiment runner, and an explicit
project-manifest input. Its files/directories are read-only. The manifest SHA-256
is `ac6cecdd3a85ecaba140e401be77c0928d08f6a6339dbe81b81b9049f32fab7f`;
the content root is `7b692617ba5a47fea3dcf0564ad490e077251736e6489df4b92b79b1db064f0b`.
These hashes identify source bytes, not proofs.

Capture reads the inventory and bytes twice and rejects observed changes. It
does not claim an atomic filesystem snapshot. Execution uses `python -I -B`,
explicit snapshot paths, and a check that every loaded `jevops` module comes
from the snapshot. The complete snapshot is validated before and after each
phase. Bytecode files are not written into it. No mutable-checkout reset,
checkout or cleanup occurs.

This isolates ordinary concurrent source edits, not hostile users who can
change filesystem permissions. The host Python installation and prepared Lean
projects/toolchains are not copied. The native verifier must still validate
their full dependency contexts before and after each request. The existing
single-build lock serializes work; scratch/reports stay within the capped
50 GB preparation volume. Execution remains trusted-local, **not an OS sandbox**.

## Precommitted experiment

Eight local Leanstral calls, four per treatment, in randomized repetition
blocks with seed 79. Both use separate system/user messages, descriptive JSON
contracts, temperature zero, a 1,024-token output cap, a 180-second socket
timeout and explicit `<|im_end|>` stop. Total allowance: eight calls / 8,192
output tokens. No retries, training or promotion are enabled.

Both arms receive the identical frozen statement, source, header, pins,
retrieved premise-name hints, numbered body lines, and 64 bounded deletion
spans from the existing `proof_slicing.deletion_variants` implementation.
Spans are **unverified edit choices**, not evidence that lines are redundant.

- `whole-body`: return a request-bound JSON tactic body, using the unchanged
  layout-preserving parser and frozen-statement joining.
- `delete-span`: return the request ID and two integer body-line endpoints
  in `delete_lines`, 1-based inclusive. The range must be one of the declared
  spans. The checker removes those lines from the exact reference and preserves
  every untouched byte, including indentation and trailing newlines.

No new tactic strings, declarations, imports, unsupported fields or forged
verification flags are accepted in a deletion action. Stale source identities,
out-of-range/reversed spans, booleans masquerading as integers and truncated
responses fail closed. An authorized edit is not an accepted theorem: every
draft still needs fresh native verification.

This deliberately changes both the output contract and the edit search space.
It is not an isolated wording experiment, nor evidence that the narrower action
space can express every useful refactoring. Greedy repetitions are not
independent samples. Historical known repairs are not supplied as answers or
credited as novel discoveries.

The plan ID is `a773eeefbaa972cfc56a75de4024248ad52926aaa68b19d88a5f112e1e0eea66`.
The existing validity screen reserves at most 27 native requests: one control
per pin (4.26.0, 4.27.0, 4.29.1), and one request per unique candidate/pin,
stopping a candidate after its first non-success. Skipped pins are explicitly
not run, not rejected. Only all-pin-valid shorter drafts qualify for a separate
fresh, order-balanced performance confirmation.

## Code and offline tests

`proof_slicing.deletion_spans` exposes the existing bounded layout vocabulary;
`apply_deletion_span` checks source identity and copies untouched text verbatim.
Neither claims to parse all of Lean or to establish proof validity. The shared
pilot runner adds `--study local-edits`, strict edit-response parsing, and
snapshot-bound execution. No new dependency stack or verifier is introduced.

Executed regressions: **252 passed, one deselected in 11.48 seconds**:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=off \
  tests/test_local_edit_proposals.py tests/test_prompt_template_pilot.py \
  tests/test_arena_snapshot.py tests/test_leanstral_prompt_lab.py \
  tests/test_leanstral.py tests/test_arena_trial.py tests/test_proof_slicing.py \
  -k 'not real_kernel_checked'
```

The Lean-dependent slicing test was deliberately deselected; offline fixture
tests are not native proof evidence. The snapshot tests cover isolation from
later workspace edits, independent imports, symlinks, altered bytes, inventory,
permissions, manifest hashes and concurrent mutation during capture.

The frozen harness also passed `--offline-self-check` with `ok: true`,
`offline_fixtures: true`, `live_health_checked: false` and
`llama_server_started: false`. This fixture check made no live model requests
and contributes no native proof or official score.

## Commands

Offline plan (no generation):

```bash
python papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py --study local-edits
```

Actual snapshot and run locations:

```bash
pilot_root=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM
pilot_base="$pilot_root/work/prompt-local-edits-20260923-MavU32"
pilot_snapshot="$pilot_base/snapshot"
pilot_digest=ac6cecdd3a85ecaba140e401be77c0928d08f6a6339dbe81b81b9049f32fab7f
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_CAS_DIR="$pilot_base/cas" \
  TMPDIR="$pilot_root/work/tmp" python -I -B \
  "$pilot_snapshot/papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py" \
  --study local-edits --generate --snapshot-manifest-sha256 "$pilot_digest" \
  --preparation-root "$pilot_root" --output "$pilot_base/run"
```

Capture used `arena_snapshot.create_snapshot` with the four include paths
`jevops`, `papers/completion/lean_refactor_arena/harness`,
`papers/completion/lean_refactor_arena/data`, and
`papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py`, plus
`inputs/projects.json` from the explicit prepared `projects-strata.json`.
The equivalent `python -I -B jevops/arena_snapshot.py create` CLI accepts these
as repeatable `--include` arguments and `--input inputs/projects.json=PATH`.
Capture/verification ran under `single-build.lock`; the snapshot receipt was
retained outside the read-only copy.

Native validity screen, after reviewing the three exact candidate sources:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_CAS_DIR="$pilot_base/cas" \
  TMPDIR="$pilot_root/work/tmp" python -I -B \
  "$pilot_snapshot/papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py" \
  --study local-edits --triage --snapshot-manifest-sha256 "$pilot_digest" \
  --preparation-root "$pilot_root" --output "$pilot_base/run" \
  --projects "$pilot_snapshot/inputs/projects.json" --elan-home "$pilot_root/work/elan" \
  --reviewed-source-sha256 ec9a67d33767579d9c4c85d4240e34556ca6b2fbbaf3e96070e2c6ac19b81403 \
  --reviewed-source-sha256 6bfe627dda3b3964618ba49880399a7fb4a1f345cdb902b1fa1bc2774e359dee \
  --reviewed-source-sha256 79bacabf0298f77bdea74f7d9ef7e6523bfa03ce8086122562955351d2cec206
```

Frozen offline harness self-check:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_CAS_DIR="$pilot_base/cas" \
  TMPDIR="$pilot_root/work/tmp" python -I -B \
  "$pilot_snapshot/papers/completion/lean_refactor_arena/harness/run_warmup.py" \
  --offline-self-check
python -I -B "$pilot_snapshot/jevops/arena_snapshot.py" verify \
  --root "$pilot_snapshot" --manifest-sha256 "$pilot_digest"
```
