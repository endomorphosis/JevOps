# Numbered deletion-ID experiment — September 23, 2026

Follow-up to the [prompt-order experiment](REFACTOR_DELETION_ORDER_EXPERIMENT.md).
The question is whether selecting a numbered edit improves valid action
selection compared with generating two line endpoints. This is an eight-call,
single-task exploratory pilot, not held-out evaluation or an Arena score.

## Generation results

| Treatment | Strict format / requests | Admitted replies | Selected deletion |
| --- | --- | --- | --- |
| endpoints-forward | 0/2 | 0 | No admissible response |
| endpoints-reverse | 0/2 | 0 | No admissible response |
| ids-forward | 1/2 | 1 | ID 1: lines 8–14 |
| ids-reverse | 2/2 | 2 | ID 64: line 12; ID 1: lines 8–14 |

Numbered IDs yielded **3/4** strict, admissible replies; endpoint arrays yielded
**0/4**. All eight requests returned successfully, with no HTTP errors, retries,
truncation or fallback. This is an observed contract/selection difference on
one small task, not a demonstrated general effect or a proof-quality gain.

Three endpoint replies had an extra closing brace; the fourth used a Markdown
fence. The rejected ID reply returned `"42"` as a string instead of an integer.
No brace/fence repair or string-to-integer coercion was performed. The admitted
IDs produced two unique sources; repeated selection of ID 1 is not a second
distinct candidate or independent proof event.

Draft 0 deletes `exact InitStatesNodup Hinit` in the base case (line 12), giving
221 local tokens versus the 224-token reference. Draft 1 deletes the entire
base-case body (lines 8–14), giving 204 tokens but leaving `case update_none =>`
empty. These are unverified size observations, not refactoring improvements.

All eight responses supplied usage: **30,104 prompt / 268 completion tokens**
(30,372 total). Summed request wall time was **33.6581 seconds**. Prompt usage
was 3,761–3,765 tokens; the ID contract cost three more input tokens per paired
request. Paid API and electricity cost were not measured. Server metadata
reported `Leanstral-1.5-119B-A6B-NVFP4.gguf` and an 8,192-token per-slot context;
these claims do not independently attest model identity.

## Native results and conclusion

All three reference controls verified. Both distinct drafts were rejected on
Lean 4.26.0: deleting line 12 led to **`simp` made no progress**; deleting lines
8–14 led to **case tag `update_some` not found** and unsolved goals after the
base-case body was removed. The four remaining candidate/pin checks were
explicitly not run under the fail-fast protocol.

The native screen completed with **five fresh requests/processes**, no native
infrastructure failures, and summed verification-request wall time of
**69.2092 seconds** (excluding initial context binding/fingerprinting). Both
phase snapshot checks report `UNCHANGED`.

**Zero verified refactoring improvements.** There was no performance
confirmation, training, promotion or official scoring. Numbered IDs improved
admissible selection in this small matched experiment, but the selected edits
were not proof-preserving. They are an experimental interface, not a new
default or demonstrated improvement in Lean reasoning.

The useful next test is to supply source/context-bound rejection feedback to
the ID selector, possibly with conservative exclusion of edits that empty a
required tactic block. That would change the information/action space and
needs a separate comparison; neither intervention was performed here. A
permitted span must never be labeled redundant merely because it has an ID.

The [evidence archive](papers/completion/lean_refactor_arena/evidence/prompt-deletion-ids-2026-09-23/)
contains raw replies, reservations, exact drafts, native receipts, snapshot
manifest, precommitted design and a
[machine-readable summary](papers/completion/lean_refactor_arena/evidence/prompt-deletion-ids-2026-09-23/summary.json).
The archive manifest binds byte lengths and SHA-256 hashes, not proofs. The
full source snapshot is retained at the private path below; it is not embedded
in the portable evidence archive.

## Precommitted design

Use `Core.InitsUpdatesComm`, the exact reference bytes and the same 64
unverified deletion spans as the previous pilot. Both output formats see the
**same catalog**, with each row containing a stable integer `edit_id` and its
`delete_lines` array. The numbered proof lines, statement, header, version pins
and retrieved premise-name hints are unchanged. The response contract appears
once, at the end of the user message, after the marked data context.

| Treatment | Response selection | Catalog display |
| --- | --- | --- |
| endpoints-forward | `delete_lines: [first, last]` | Original order |
| endpoints-reverse | `delete_lines: [first, last]` | Reverse order |
| ids-forward | `edit_id: integer` | Original order |
| ids-reverse | `edit_id: integer` | Reverse order |

Every response must also contain the exact current `request_id`, and no other
fields. IDs remain attached to the same span when display order reverses; they
are not list positions. The catalog content hash binds the full frozen record
(including context/pins) and source bytes. The request nonce binds the canonical
case and repetition, paired across all four treatments. No previous responses,
diagnostics, winning edits, preferred IDs or repair solutions are supplied.

Two repetition blocks, randomized with seed 109, give eight requests total.
All arms use local `leanstral_local`, logical model `Leanstral`, temperature
zero, 1,024 output tokens, a 180-second timeout, `<|im_end|>` stop and at least
8,192 declared context tokens per slot. Total output allowance is 8,192 tokens.
There are no retries, paid API/fallback routes, server restarts or downloads.

The input context is identical between endpoint and ID arms within each
display order. Contract wording/length necessarily differs, so this is a
comparison of output representations, not a pure equal-token wording test.
Unlike the preceding pilot, **both** arms see the numbered catalog; historical
rates are descriptive only, not matched controls. Greedy repetitions on one
previously studied task are not independent statistical samples.

## Admission and verification

The existing strict JSON parser and source-bound deletion checker are reused.
An ID must be an integer, not a Boolean, string, float or display position.
Missing/stale catalog identity, undeclared IDs, foreign request IDs, duplicate
fields, model-supplied source/verification flags, fences and malformed wrappers
fail closed. No ID is clamped, remapped or silently repaired. Known terminal
marker normalization remains separately recorded. This is **client-side
validation**, not grammar-constrained model decoding.

The client resolves an ID to an exact existing span and preserves all other
source bytes. Selecting an allowed edit is not a proof. Primary measurements
are strict format compliance and admitted edit selection; secondary outcomes
include native verification, measured usage and request wall time.

Only exact reviewed sources proceed to fresh native checks, with three Lean
pins (4.26.0, 4.27.0, 4.29.1), one reference control per pin, cache disabled,
at most 27 requests and fail-fast candidate checks. Remaining checks after a
non-success are explicitly not run. Only shorter all-pin-valid drafts qualify
for separate fresh, order-balanced performance confirmation. No training,
promotion or official scoring occurs in this pilot.

## Implementation and isolation

The existing runner adds `--study deletion-ids`, a bounded source-bound catalog
and ID resolution inside its shared deletion parser. Old study prompts and
endpoint semantics have regression coverage. New tests compare every ID's
constructed source with its endpoint equivalent and check stale context,
invalid/forged responses, stable IDs under reversal, matched prompts, budget
reservations, no automatic execution, native review gating and snapshot gating.

The first regression run caught a current transport-validation bug:
`role: []` raised unhandled `TypeError` during set membership. A narrow string
type guard in `leanstral._messages_ok` restores the existing validation-error
contract; dict, null and integer roles are also tested. No endpoint or
execution restrictions were relaxed.

Execution uses a fresh read-only source snapshot and isolated Python imports,
with checks before and after each phase. The existing shared lock serializes
work inside the 50 GB preparation volume. Host Python and prepared Lean
dependencies are not copied; native requests retain their context checks.
Trusted-local scratch is not an OS sandbox. SHA-256 hashes identify content,
not proofs or CIDs.

Offline preview:

```bash
python papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py --study deletion-ids
```

## Offline regression command

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --test-seal=off \
  tests/test_deletion_id_pilot.py tests/test_deletion_order_pilot.py \
  tests/test_local_edit_proposals.py tests/test_prompt_template_pilot.py \
  tests/test_arena_snapshot.py tests/test_leanstral_prompt_lab.py \
  tests/test_leanstral.py tests/test_arena_trial.py tests/test_proof_slicing.py \
  -k 'not real_kernel_checked'
```

Result after the validation fix: **282 passed, one deliberately deselected in
12.11 seconds**. The initial run had 278 passed, one failure and one deselected;
the failure and its fix are described above. The excluded native slicing test
uses installed Lean. These fixture regressions are not native proof evidence
or a complete repository test run.

## Frozen execution commands

The source snapshot contains 228 files / 4,769,062 bytes, including the runtime,
harness, corpus, runner, five relevant test files, precommitted design and the
prepared project manifest. Snapshot manifest SHA-256:
`764fd200a65d7c44a66034b72e77023f7a93fe3328357bcedfe38be3e55f42f5`.
Plan ID: `0c12f96ec8a9b7d6142a59c095b53195eb424a5ddfc73e3980b284c6e8f0a52b`.
Catalog content hash: `52677802aa9a72d367b5a883b0b552a21d71b1d948af13ef7e1026e12f052219`.

Actual generation command:

```bash
id_prep=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM
id_base="$id_prep/work/prompt-deletion-ids-20260923-CJZSJi"
id_snapshot="$id_base/snapshot"
id_digest=764fd200a65d7c44a66034b72e77023f7a93fe3328357bcedfe38be3e55f42f5
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_CAS_DIR="$id_base/cas" \
  TMPDIR="$id_prep/work/tmp" python -I -B \
  "$id_snapshot/papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py" \
  --study deletion-ids --generate --snapshot-manifest-sha256 "$id_digest" \
  --preparation-root "$id_prep" --output "$id_base/run"
```

Actual native command, after reviewing both exact source-bound deletions:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_CAS_DIR="$id_base/cas" \
  TMPDIR="$id_prep/work/tmp" python -I -B \
  "$id_snapshot/papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py" \
  --study deletion-ids --triage --snapshot-manifest-sha256 "$id_digest" \
  --preparation-root "$id_prep" --output "$id_base/run" \
  --projects "$id_snapshot/inputs/projects.json" --elan-home "$id_prep/work/elan" \
  --reviewed-source-sha256 d3b0f4b8ccc3fd6339156b886fa9567a690edf54d4e7165bd0bbc1aee07e458d \
  --reviewed-source-sha256 baabfe7660cbfa6494a1a09cf14341c04d611df70be17cedc3739dba2d8e939b
```
