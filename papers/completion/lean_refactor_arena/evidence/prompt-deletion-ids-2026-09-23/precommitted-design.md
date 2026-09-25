# Numbered deletion-ID experiment — September 23, 2026

Follow-up to the [prompt-order experiment](REFACTOR_DELETION_ORDER_EXPERIMENT.md).
The question is whether selecting a numbered edit improves valid action
selection compared with generating two line endpoints. This is an eight-call,
single-task exploratory pilot, not held-out evaluation or an Arena score.

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
or a complete repository test run. Results and exact execution commands follow
after the bounded experiment.
