# Deletion-prompt ordering experiment — September 23, 2026

Follow-up to the [local-edit pilot](REFACTOR_LOCAL_EDIT_EXPERIMENT.md). This
experiment interprets reordering as **presentation order**, not a permutation
of executable Lean tactics or dependent hypotheses. The exact target,
reference bytes, numbered proof lines and set of 64 allowed deletion spans
remain fixed. Changing Lean execution order is a separate semantic experiment.

## Precommitted comparison

Eight local Leanstral calls on the previously studied public warm-up problem
`Core.InitsUpdatesComm`: two repetition blocks, four treatments per block,
randomized with seed 97. This is not held-out evaluation or an official score.

| Treatment | Response contract | Allowed deletion spans |
| --- | --- | --- |
| before-forward | Before context | Existing order |
| before-reverse | Before context | Reverse order |
| after-forward | After context | Existing order |
| after-reverse | After context | Reverse order |

The response contract is in the **user message in every treatment**, outside
the marked data context. System instructions and contract wording are identical;
each request contains the contract exactly once. Each repetition uses the same
request nonce across its four arms. The reference and numbered proof lines
stay in their original order. Only the presentation of allowed span choices
is reversed, not their endpoints or meaning. All four prompts have equal
character counts; actual tokenizer counts are measured, not assumed equal.

The earlier pilot placed the contract in the system message. Its results may
be mentioned descriptively, but are not a matched control for this experiment.
No historical response, failed edit, known repair or winning span is supplied
to the model. Greedy repetitions are not independent statistical samples.

Fixed generation settings: local `leanstral_local` route, logical model
`Leanstral`, temperature zero, 1,024 output tokens per request, 180-second
timeout, `<|im_end|>` stop, at least 8,192 declared context tokens per slot.
Total allowance: eight calls / 8,192 output tokens. No retries, paid API,
fallback, server restart, downloads or training are part of this experiment.

Primary observations are strict response-contract compliance and admitted
deletion actions. The parser is unchanged: exactly `request_id` and
`delete_lines: [first, last]`, bound to the current request and a declared span.
Known terminal-marker normalization is separately recorded; fences, tool-call
wrappers, extra fields, malformed arrays and truncated output are not salvaged.
Admission constructs an unverified source-bound edit, not a proof.

Only exact, reviewed admitted sources proceed to fresh native verification on
Lean 4.26.0, 4.27.0 and 4.29.1, with one reference control per pin, no evidence
cache and fail-fast candidate checks. At most 27 native requests are allowed.
Only a shorter all-pin-valid candidate qualifies for separate, fresh,
order-balanced performance confirmation. Neither format compliance nor a
shorter rejected proof counts as an improvement.

## Implementation and isolation

The existing pilot runner adds `--study deletion-order`; the shared parser,
deletion checker and native verifier are reused unchanged. No new framework
or dependency is introduced. The new offline tests check paired prompts,
identical source/action sets, exact contract movement, equal prompt lengths,
unchanged previous-study prompts, strict checking, reservation idempotency,
native review gating and mandatory source snapshots for live execution.

Execution uses a fresh read-only snapshot, isolated Python imports, and
before/after snapshot checks. One shared preparation lock serializes work,
within the existing 50 GB capped volume. Host Python and prepared Lean
dependencies are not copied; native requests retain their own context checks.
Trusted-local scratch execution is not an OS sandbox. SHA-256 hashes identify
content and do not establish proof validity.

Offline preview (makes no model requests):

```bash
python papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py --study deletion-order
```

Results and exact execution locations will be appended after the bounded run.

Executed offline regression command:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --test-seal=off \
  tests/test_deletion_order_pilot.py tests/test_local_edit_proposals.py \
  tests/test_prompt_template_pilot.py tests/test_arena_snapshot.py \
  tests/test_leanstral_prompt_lab.py tests/test_leanstral.py \
  tests/test_arena_trial.py tests/test_proof_slicing.py -k 'not real_kernel_checked'
```

Result: **257 passed, one deliberately deselected in 14.93 seconds**. The
excluded slicing test uses installed Lean; these are offline regression tests,
not native proof evidence or the complete repository suite.
