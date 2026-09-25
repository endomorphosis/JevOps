# Rejection-feedback edit selection — September 23, 2026

Follow-up to the [numbered edit-ID experiment](REFACTOR_DELETION_ID_EXPERIMENT.md).
This experiment tests whether historical, source-bound native diagnostics help
the model choose a different, proof-preserving deletion. It does not train
weights, prune the action catalog, or reuse historical receipts as new proofs.

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
repository test suite. Experiment outcomes follow after execution.
