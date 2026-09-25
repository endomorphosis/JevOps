# Rejection-feedback edit selection — September 23, 2026

Follow-up to the [numbered edit-ID experiment](REFACTOR_DELETION_ID_EXPERIMENT.md).
This experiment tests whether historical, source-bound native diagnostics help
the model choose a different, proof-preserving deletion. It does not train
weights, prune the action catalog, or reuse historical receipts as new proofs.

## Generation results

| Treatment | Strict, admitted replies / attempts | Selected IDs | Previously rejected exact sources |
| --- | --- | --- | --- |
| no-feedback-forward | 1/2 | 1 | 1/1 admitted |
| no-feedback-reverse | 1/2 | 1 | 1/1 admitted |
| feedback-forward | 0/2 | None admitted | Not measurable |
| feedback-reverse | 1/2 | 64 | 1/1 admitted |

Combined, feedback yielded **1/4** admissible responses, versus **2/4** without
feedback. Every admitted reply repeated a previously rejected exact source:
ID 64 deletes line 12; ID 1 deletes lines 8–14. Neither condition produced an
admitted new source or demonstrated avoidance of the prior failures. Malformed
replies are not counted as successful avoidance. Two control selections of
ID 1 are one distinct candidate, not independent proof discoveries.

The five rejected envelopes contained tool-call-shaped junk, a Markdown fence,
string-valued IDs, or an extra field/closing brace. No strings were coerced to
integers, wrappers stripped, or extra fields salvaged. All eight requests
returned with usage; there were no HTTP failures, retries, fallback or output
truncation. No tool was invoked from generated text.

Usage: **35,836 prompt / 278 completion tokens** (36,114 total); summed client
request wall time **39.7769 seconds**. Feedback cost 4,940 input tokens per call
versus 4,019 for controls—921 additional tokens per paired request. Paid API and
electricity cost were not measured. The longer treatment context is part of
the intervention, not an isolated wording contrast. These small greedy samples
do not establish a general harmful or beneficial effect of rejection feedback.

The server reported `Leanstral-1.5-119B-A6B-NVFP4.gguf` with **32,768 context
tokens per slot**, above the precommitted 8,192-token minimum. This differs from
the earlier ID pilot's reported 8,192 allocation; cross-study rate comparisons
would therefore have another confound. Visible metadata stayed fixed across
this run's paired treatments. This experiment did not restart or reconfigure
the server, and its metadata is not independent model/weight attestation.

## Native results and conclusion

The screen completed with **five fresh native requests/processes**: all three
reference controls verified; both candidate sources were rejected on 4.26.0.
ID 64 again produced `simp` made no progress. ID 1 again produced a missing
`update_some` case tag and unsolved goals after removal of the base-case body.
The four later candidate/version checks were explicitly not run under the
fail-fast rule. No historical receipt was substituted for these fresh checks.

There were no native infrastructure failures. Summed verification-request
wall time was **70.0230 seconds**, excluding initial context binding and
fingerprinting. Generation and native snapshot checks both report `UNCHANGED`.

**Zero verified refactoring improvements.** No performance confirmation,
training, promotion or official scoring occurred. This is a negative result
for this feedback treatment on this task: no newly admitted source, repeated
known failures, and lower observed format compliance than its matched control.
It is not a general claim that feedback is ineffective.

Before another prompt comparison, the useful next experiment is a bounded,
deterministic Lean-checked screen of the deletion catalog to establish whether
it contains any valid improvements at all. That separates action-space quality
from model selection quality. Such a screen was **not** performed here.

The [evidence archive](papers/completion/lean_refactor_arena/evidence/prompt-deletion-feedback-2026-09-23/)
contains raw replies, reservations, exact drafts, fresh native receipts,
snapshot manifest, frozen historical inputs, precommitted design and a
[machine-readable summary](papers/completion/lean_refactor_arena/evidence/prompt-deletion-feedback-2026-09-23/summary.json).
Its manifest binds file hashes and sizes; it is not proof. The complete source
snapshot remains at the private location below, outside the portable archive.

## Precommitted comparison

Eight local Leanstral requests on the previously studied public warm-up task
`Core.InitsUpdatesComm`: two repetition blocks, four treatments, randomized
with seed 127. Both conditions use numbered edit IDs and contract-last prompts.

| Treatment | Historical rejection observations | Catalog display |
| --- | --- | --- |
| no-feedback-forward | Empty | Original order |
| no-feedback-reverse | Empty | Reverse order |
| feedback-forward | Two bound native rejections | Original order |
| feedback-reverse | Two bound native rejections | Reverse order |

The statement, source bytes, numbered body lines, all 64 permitted deletions,
stable ID meanings, system instructions and response contract stay fixed.
Both conditions receive the same instruction to use any supplied diagnostics
to avoid repeating an unsuccessful unchanged edit. Within each display order,
only the `historical_rejections.observations` list differs. The metadata wrapper
is shared; it supplies no rejected IDs when the list is empty. Request nonces
are paired across all four treatments within each repetition.

The feedback consists of the preceding experiment's rejected exact sources:
ID 1 (delete lines 8–14) and ID 64 (delete line 12), both checked on Lean 4.26.0.
It contains candidate/context/request identities, dependency/verifier identity,
pin and a bounded first diagnostic. No winning edit, new tactic, human repair
or evidence from this experiment is supplied. The first diagnostic is capped
at 1,000 characters, and truncation/omitted diagnostics are explicit.

Primary observations: fresh all-pin-valid edits, and whether admitted proposals
repeat those two exact rejected sources. Secondary observations: strict format,
admission, measured usage and wall time. Malformed output is not counted as
successful avoidance. Feedback makes prompts longer; this is not an equal-token
wording comparison or a statistically powered/held-out evaluation.

Fixed settings: `leanstral_local`, logical model `Leanstral`, temperature zero,
1,024 output tokens per request, 180-second timeout, `<|im_end|>` stop, and at
least 8,192 declared context tokens per slot. Eight calls / 8,192 output-token
allowance. No retries, paid API route, fallback, model installation or restart.

## Historical and current trust boundaries

Three explicit files from the previous ID-pilot archive are consumed:
`plan.json`, `native-plan.json`, and `native-triage.json`. Their byte lengths and
SHA-256 hashes must match the archive manifest, whose externally supplied hash
is `6626bad2552508228af3096405b42911a03d430c7f8775c2e91a9baaf75a29ed`.
Other manifest entries are not read. All inputs are copied into the new source
snapshot; no ambient history discovery or mutable-file reads occur in the run.

The adapter reuses `refactor_prompts._examples` for record, candidate, context,
version pin, request, measurement, dependency and diagnostic consistency
checks. It reconstructs every candidate as an exact catalog deletion. Repeated
observations are deduplicated; unrun checks and infrastructure errors are never
turned into semantic negatives. Malformed or mismatched history fails closed.
These checks detect inconsistency, not authenticity. Historical rejection is
about a particular candidate and context, not falsity of the target theorem.

**All 64 actions remain enabled, including IDs 1 and 64.** A model can ignore
the hints and select them again. Every admitted source—including a repeat—must
undergo fresh native checks; no negative cache is populated from the history.
The previous verification context is retained as historical data, not declared
to be the current context. No online updates to feedback occur during the run.

Native verification uses the existing reviewed-source gate, reference controls
on Lean 4.26.0, 4.27.0 and 4.29.1, cache disabled, at most 27 requests, and
candidate fail-fast after non-success. Repeated selections of identical source
bytes are one candidate. Only shorter all-pin-valid candidates qualify for a
separate fresh, order-balanced performance confirmation. No automatic training,
promotion or official Arena scoring occurs.

## Implementation and isolation

The existing pilot runner adds `--study deletion-feedback` with explicit
`--feedback-history` and `--feedback-manifest-sha256` arguments. Its adapter
converts the saved native rows into the existing history checker's in-memory
format; it does not create a second verifier or agent framework. The shared
strict ID parser, deletion checker and native verifier remain unchanged.

Offline tests cover historical binding/tampering, bounded file reads, duplicate
observations, transient failures, unrun receipts, matched prompts, unchanged
older prompts, all 64 enabled IDs, reservations/resume, no automatic proof
admission, native review gating and mandatory snapshot/history identities.

Execution uses a fresh read-only snapshot with isolated Python imports and
phase-boundary checks. The existing shared lock and 50 GB volume remain in
force. Prepared Lean dependencies and host Python are not copied and retain
their separate native context checks. Trusted-local scratch is not an OS
sandbox; content hashes are not proofs or CIDs.

Offline preview:

```bash
python papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py \
  --study deletion-feedback \
  --feedback-history papers/completion/lean_refactor_arena/evidence/prompt-deletion-ids-2026-09-23 \
  --feedback-manifest-sha256 6626bad2552508228af3096405b42911a03d430c7f8775c2e91a9baaf75a29ed
```

Offline regression command:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --test-seal=off \
  tests/test_deletion_feedback_pilot.py tests/test_deletion_id_pilot.py \
  tests/test_deletion_order_pilot.py tests/test_local_edit_proposals.py \
  tests/test_prompt_template_pilot.py tests/test_refactor_prompts.py \
  tests/test_arena_snapshot.py tests/test_leanstral_prompt_lab.py \
  tests/test_leanstral.py tests/test_arena_trial.py tests/test_proof_slicing.py \
  -k 'not real_kernel_checked'
```

Result: **378 passed, one deliberately deselected in 18.47 seconds**. The
installed-Lean slicing test is excluded from this offline suite. These are
targeted fixture regressions, not native proof evidence or the entire
repository test suite.

## Frozen execution commands

Snapshot: 234 files / 4,950,934 bytes, including the runtime, harness, corpus,
runner, six relevant tests, precommitted design, project manifest, and four
explicit historical input files. Manifest SHA-256:
`63a4d9ed09b8adff16b6ce7d66696483f9490f6f7cd6b378ef9dafd8ee6e6f88`.
Plan ID: `7a3dfdbc34cc58a3d74a7b7a975795d086f3e9b18daa2967e20c8d2b3b2b166c`.

Actual generation command:

```bash
feedback_prep=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM
feedback_base="$feedback_prep/work/prompt-deletion-feedback-20260923-ZEU0J5"
feedback_snapshot="$feedback_base/snapshot"
feedback_digest=63a4d9ed09b8adff16b6ce7d66696483f9490f6f7cd6b378ef9dafd8ee6e6f88
history_digest=6626bad2552508228af3096405b42911a03d430c7f8775c2e91a9baaf75a29ed
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_CAS_DIR="$feedback_base/cas" \
  TMPDIR="$feedback_prep/work/tmp" python -I -B \
  "$feedback_snapshot/papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py" \
  --study deletion-feedback --generate --snapshot-manifest-sha256 "$feedback_digest" \
  --feedback-history "$feedback_snapshot/inputs/history" --feedback-manifest-sha256 "$history_digest" \
  --preparation-root "$feedback_prep" --output "$feedback_base/run"
```

Actual native command, after inspecting both generated exact sources:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_CAS_DIR="$feedback_base/cas" \
  TMPDIR="$feedback_prep/work/tmp" python -I -B \
  "$feedback_snapshot/papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py" \
  --study deletion-feedback --triage --snapshot-manifest-sha256 "$feedback_digest" \
  --feedback-history "$feedback_snapshot/inputs/history" --feedback-manifest-sha256 "$history_digest" \
  --preparation-root "$feedback_prep" --output "$feedback_base/run" \
  --projects "$feedback_snapshot/inputs/projects.json" --elan-home "$feedback_prep/work/elan" \
  --reviewed-source-sha256 d3b0f4b8ccc3fd6339156b886fa9567a690edf54d4e7165bd0bbc1aee07e458d \
  --reviewed-source-sha256 baabfe7660cbfa6494a1a09cf14341c04d611df70be17cedc3739dba2d8e939b
```
