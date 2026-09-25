# Deletion-prompt ordering experiment — September 23, 2026

Follow-up to the [local-edit pilot](REFACTOR_LOCAL_EDIT_EXPERIMENT.md). This
experiment interprets reordering as **presentation order**, not a permutation
of executable Lean tactics or dependent hypotheses. The exact target,
reference bytes, numbered proof lines and set of 64 allowed deletion spans
remain fixed. Changing Lean execution order is a separate semantic experiment.

## Generation results

| Treatment | Returned responses / attempts | Strict contract | Admitted deletions | Other outcomes |
| --- | --- | --- | --- | --- |
| before-forward | 2/2 | 0/2 | 0 | One truncated proof-body response; one malformed contract |
| before-reverse | 1/2 | 1/1 returned | 0 | One undeclared span; one HTTP 500 |
| after-forward | 2/2 | 2/2 | 0 | Two undeclared spans |
| after-reverse | 2/2 | 2/2 | 1 | One undeclared span |

Placing the contract **after** context gave strict JSON in 4/4 requests;
placing it **before** gave strict JSON in 1/3 returned responses, with one
additional infrastructure failure. These denominators distinguish the HTTP
failure from a model-generated invalid answer. No failed request was retried.
The observed contrast favors contract-last for formatting in this small pilot,
not a statistically established effect or improved theorem-proving quality.

Four well-formed replies chose undeclared spans: `[1, 14]`, `[1, 46]` (twice),
and `[1, 43]`. They were rejected without constructing a candidate. The one
admitted reply selected `[16, 46]`, an allowed deletion from the exact reference.
Its 72-token draft (versus 224 reference tokens) leaves `case update_some ... =>`
without a body. Native Lean 4.26.0 rejected it with
`unexpected end of input; expected '{'`. This is not a 68% proof-size improvement:
it is an invalid proof. No wrapper removal or repair was used to manufacture
another candidate.

All prompts contain 7,486 characters. Available usage reports show 2,857 prompt
tokens in repetition 0 and 2,850 in repetition 1, matching within each paired
block. Seven requests supplied usage: **19,978 prompt / 1,231 completion tokens**.
The HTTP 500 supplied no usage, so the complete eight-request token total is
**unknown**, not 21,209. Summed client request wall time was **126.2877 seconds**,
including the failed request. Paid API and electricity cost were not measured.
The server reported `Leanstral-1.5-119B-A6B-NVFP4.gguf` and an 8,192-token
per-slot context; model identity is not independently attested.

## Native outcome and interpretation

The screen completed with **four fresh native requests/processes**: three
verified reference controls and the rejected draft on 4.26.0. Its 4.27.0 and
4.29.1 checks were explicitly not run after rejection, as precommitted. There
were no native infrastructure failures. Summed verification-request wall time
was **57.5837 seconds**, excluding initial context binding/fingerprinting.
Both generation and native snapshot checks report `UNCHANGED`.

**Zero verified refactoring improvements.** No performance confirmation,
selection, training, promotion or official scoring was performed. Reversing
the span list alone did not resolve semantic validity. Contract-last is a
promising formatting treatment for another controlled test, not a new default
or a demonstrated proof-quality gain. An informative next experiment would
compare these endpoint arrays with source-bound enumerated edit IDs; that
contract change and any grammar-constrained decoding remain untested here.

The [evidence archive](papers/completion/lean_refactor_arena/evidence/prompt-deletion-order-2026-09-23/)
includes raw responses, reservations, the exact draft, verification receipts,
precommitted design, snapshot manifest and a
[machine-readable summary](papers/completion/lean_refactor_arena/evidence/prompt-deletion-order-2026-09-23/summary.json).
An archive manifest binds file hashes and sizes; it is not proof. The complete
read-only source snapshot remains at the private location below, not in the
portable archive.

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

## Frozen execution

The snapshot contains 225 files / 4,725,703 bytes, including the runtime,
harness, corpus, runner, three pilot test files, precommitted design note and
explicit project-manifest input. Snapshot manifest SHA-256:
`7b15d0608071212d2cd915e26e90812741a9dae09f338ec7cfab634b48a16b8b`.
Experiment plan ID:
`53d77e0b542f89304a0864c3858b17468f58c4ff30790f7fc3201f432e576ed8`.

Actual generation command:

```bash
order_prep=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM
order_base="$order_prep/work/prompt-deletion-order-20260923-MqhR8i"
order_snapshot="$order_base/snapshot"
order_digest=7b15d0608071212d2cd915e26e90812741a9dae09f338ec7cfab634b48a16b8b
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_CAS_DIR="$order_base/cas" \
  TMPDIR="$order_prep/work/tmp" python -I -B \
  "$order_snapshot/papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py" \
  --study deletion-order --generate --snapshot-manifest-sha256 "$order_digest" \
  --preparation-root "$order_prep" --output "$order_base/run"
```

Actual native command, after inspecting the exact source-bound deletion:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_CAS_DIR="$order_base/cas" \
  TMPDIR="$order_prep/work/tmp" python -I -B \
  "$order_snapshot/papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py" \
  --study deletion-order --triage --snapshot-manifest-sha256 "$order_digest" \
  --preparation-root "$order_prep" --output "$order_base/run" \
  --projects "$order_snapshot/inputs/projects.json" --elan-home "$order_prep/work/elan" \
  --reviewed-source-sha256 99cac8c59bfc36e1acba41c1525a0175b9d8a10bed3bc31371a731e694eab8c7
```

## Offline validation

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
