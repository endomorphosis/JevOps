# Leanstral contract wording × output allowance — September 23, 2026

This is a fresh follow-up to the [message-role experiment](REFACTOR_CONTRACT_EXPERIMENT.md).
It does not repair or relabel earlier drafts. The public warm-up problem
`Core.InitsUpdatesComm` has already been studied; this is not held-out prompt
selection, a model-quality ranking or an official Arena score.

## Generation results

| Treatment | Format + intake accepted | Other outcomes | Output tokens used |
| --- | --- | --- | ---: |
| Placeholder, 1,024 | 0/2 | Two JSON contract failures | 1,013 |
| Placeholder, 3,072 | 0/2 | One JSON failure; one unsupported proof envelope | 662 |
| Descriptive, 1,024 | 2/2 | None at intake | 975 |
| Descriptive, 3,072 | 0/2 | One JSON failure; one output-limit truncation | 3,558 |

All eight requests returned usage metadata: **10,316 prompt tokens and 6,208
output tokens**, with summed request wall time **265.6065 seconds**. No new
model calls were made during verification. Hosted API and electricity costs
were not measured. There were no retries, empty completions or provider
fallbacks in this generation run.

The two intake-accepted drafts have 179 and 223 local tokens versus the
224-token reference. Those are **unverified lengths, not scores**. Both raw
JSON tactic strings put the first tactic at column zero and subsequent peers
two spaces deeper; the layout-preserving parser did not manufacture this
inconsistency or repair it. The first also contains an apparent `And.intu`
typo and substantive omissions. No corrected variant is included in the run.

Observable contract failures include repeated JSON objects, malformed trailing
markers and a leaked chat-role marker. One otherwise parsed JSON response
contains a whole theorem in its tactic field and is rejected at intake. These
are output symptoms, not a diagnosis of model weights or server configuration.
The larger allowance did not yield an additional admitted draft; one response
still used all 3,072 tokens without producing an admissible final body.

The 2/2 descriptive/1,024 result concerns **intake only**. It is not proof success
or sufficient evidence to select a generally superior prompt. The countervailing
0/2 result at 3,072 and the small, previously studied task must remain visible.

## Verification context change

The first native invocation refused to execute because `jevops/llm_router.py`
and `jevops/arena_lean.py` changed elsewhere in the shared checkout after the
generation plan was saved. No receipt was produced and no process was charged
by that refused invocation. The original generation plan and reports were not
edited, and unrelated changes were not reverted.

Verification therefore uses a **new, explicitly identified epoch** with the
current verifier implementation and fresh controls. `--recheck-generation`
copies the original generation report and draft bytes into a new empty directory,
records the original plan identity and hashes, and performs no generation.
Only implementation changes may be rebound; changed tasks, prompts, budgets
or native protocols are rejected. The native report records both the new
epoch's plan ID and the original generation plan ID; each receipt is bound to
its new verification context. No old proof receipt is reused.

This is a disclosed departure from the original same-code phase plan, not a
successful resume of it. The unchanged proposals can be evaluated under a new
verification context, but results must not be mislabeled as measurements under
the old implementation. The immutable original plan ID is
`d364e4d60ffce58002def6f5373f75d3931b47858369048c0cdc385d89748433`.

## Native outcome: incomplete control coverage

The verification epoch is
`8836b3d28ee7309103cfe6dceac180617901ad15f5d1d5725c71fd56f9f0073d`.
It made five fresh native requests/processes:

- Reference controls verified on 4.26.0 and 4.27.0.
- Both generated drafts were rejected on 4.26.0 with unsolved goals and
  `unexpected token 'exists'; expected command`.
- Four later candidate/version combinations were not run after those failures.
- The 4.29.1 reference control returned **ERROR**, with
  `dependencies_changed_start_new_context`; it is not a proof rejection or pass.

`arena_lean.py` changed again during this epoch. The after-execution dependency
check invalidated the final observation. The report status is therefore
**CONTROL_FAILED**, not COMPLETE. Earlier receipts remain historical evidence
about their exact contexts; they are not silently made applicable to the current
checkout. There is no complete three-pin control check for this experiment.

**Zero verified refactoring improvements; no performance confirmation or
promotion.** Both drafts already failed a required pin, but the concurrent
code changes also prevent treating this as an uninterrupted, fixed-code native
comparison. Further comparative native runs need a stable code snapshot or
coordination with the ongoing edits. This bounded run stops without repeatedly
restarting verification or spending additional model calls.

The [archived evidence](papers/completion/lean_refactor_arena/evidence/prompt-output-budget-2026-09-23/)
keeps the original generation plan and the separate `native-epoch` together.
The [summary](papers/completion/lean_refactor_arena/evidence/prompt-output-budget-2026-09-23/summary.json)
records file hashes, actual usage, outcome counts, both epoch identities and
post-verification code drift. Copies are not independent verification events.

## Frozen design

Eight local Leanstral calls: two repetitions of four treatments, randomized
within repetition blocks using seed 67. Both factors are crossed:

| JSON contract wording | Output-token cap |
| --- | --- |
| Existing placeholder object | 1,024 |
| Existing placeholder object | 3,072 |
| Descriptive field specification | 1,024 |
| Descriptive field specification | 3,072 |

All treatments use separate system/user messages, the same exact frozen
statement, reference, header, version pins and retrieved premise-name hints.
No historical repair or diagnostics are added. Within a wording treatment,
the messages and request ID are identical at both output allowances. Across
wordings, only the contract instruction changes, not the context or request
binding. The new wording describes both JSON string fields and escaped
newlines without providing a copyable tactic-value placeholder. This tests
a verbal field specification against an example object, not an isolated
single-word deletion.

The shared settings are temperature zero, the explicit `<|im_end|>` stop,
the existing local `leanstral_local` route and `Leanstral` model alias, and a
300-second socket timeout. The timeout is raised for **all** treatments,
so only the designated output allowance varies between budget arms. Socket
timeouts are not whole-run deadlines. The upper generation allowance is
**eight calls / 16,384 output tokens**. Equal call counts do not imply equal
token budgets or costs. Greedy repetitions are not independent samples.

The server must declare at least 8,192 context tokens per slot before any
generation. Prompt lengths are 3,690 and 3,825 characters respectively; these
are not exact token counts. Actual response usage is reported separately.
The observed server metadata remains a claim, not weight/hardware attestation.
No server restart, parameter change, download or dependency build is requested.

The plan is persisted before calls, including complete messages, settings,
schedule and implementation hashes. Per-slot output allowances are reserved
before work. Completed or interrupted slots are never retried; changed
code/plans or visible serving metadata prohibit resuming the same directory.

## Admission and verification

The strict response parser is unchanged: exact JSON fields and request ID,
no truncated responses or fence salvage. Parsed tactic bodies retain relative
indentation. No manual tactic or indentation repair is part of this experiment.
Format compliance and lexical intake do not establish a proof.

Generation never executes drafts. After operator review of each exact source,
the existing native adapter performs fresh checks under the shared preparation
lock, using private scratch within the capped 50 GB volume and a minimal
environment. This is **trusted-local execution, not an OS sandbox**.

The predeclared validity screen uses pins 4.26.0, 4.27.0 and 4.29.1, one
reference control per pin, one attempt per candidate/pin, reference-first
branch order, and no receipt cache. A candidate stops after its first
non-success; remaining pins are `NOT_RUN_AFTER_NON_SUCCESS`, not failed
proofs. Maximum allowance is 27 requests. A failed control stops subsequent
verification. Incremental receipts persist; a reserved triage cannot be rerun.

Only an all-pin-valid shorter candidate qualifies for fresh performance
confirmation with both branch orders and two repetitions using `arena_trial`.
No automatic promotion, positive teacher creation or training takes place.
The primary outcome is a verified refactoring improvement; JSON acceptance,
truncation and measured token usage are secondary observations.

## Reproduction

Offline plan:

```bash
python papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py --study output-budget
```

Executed generation:

```bash
pilot_root=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM
pilot_out="$pilot_root/work/prompt-output-budget-20260923-z9P4dm"
env JEVOPS_REGISTER_LRA_HOOKS=0 TMPDIR="$pilot_root/work/tmp" \
  python papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py \
  --study output-budget --generate --preparation-root "$pilot_root" --output "$pilot_out"
```

Use a new directory for a new experiment. Generation does not grant approval
to execute a candidate; `--triage` additionally requires explicit prepared
project/Elan paths and every reviewed source SHA-256.

Executed fresh-epoch verification:

```bash
pilot_native="$pilot_root/work/prompt-output-budget-native-20260923-1lOKwG"
env JEVOPS_REGISTER_LRA_HOOKS=0 TMPDIR="$pilot_root/work/tmp" \
  python papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py \
  --study output-budget --triage --recheck-generation "$pilot_out" \
  --preparation-root "$pilot_root" --output "$pilot_native" \
  --projects "$pilot_root/work/projects-strata.json" --elan-home "$pilot_root/work/elan" \
  --reviewed-source-sha256 4138b228fa925512b54e4248d75e4aab7a0366e12f84b091fe9ff60c2afe3de6 \
  --reviewed-source-sha256 9fbe690262148aedab8617939fc24736657b2ec7566337f5fcf1b8c06035dfb7
```

## Changes and regression coverage

`jevops/leanstral_prompt_lab.py` adds opt-in `Arm.json_contract_style` with
`placeholder` (unchanged default) and `descriptive` choices; the latter is
JSON-only. The shared experiment runner adds `--study output-budget`, a
restricted per-treatment output allowance, aggregate allowance checks and a
minimum declared serving-context check. Only the output cap may be overridden
per treatment; endpoint/provider overrides are rejected.

Tests assert matched contexts/messages, exact preservation of earlier default
prompts, actual transport settings, invalid/zero/non-integer allowances,
aggregate limits, context preflight and at-most-once resume. Fixture model
responses are not live or native proof evidence.
Additional epoch tests require immutable generation copies, distinguish old
generation from new verification identities, reject modified imports and
changed experiment protocols, and prohibit generation from a verification-only
epoch. No silent "ignore code mismatch" switch was added.

Executed offline regressions, **305 passed in 26.32 seconds**:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=off \
  tests/test_prompt_template_pilot.py tests/test_leanstral_prompt_lab.py \
  tests/test_leanstral_prompt_feedback.py tests/test_lean_tactic_layout.py \
  tests/test_leanstral.py tests/test_refactor_prompts.py tests/test_arena_trial.py
```

This is targeted coverage, not a full repository suite run. Previous experiment
reports and saved receipts are unchanged.

After the concurrent adapter changes and new epoch handling, the final command
was the same test list plus `tests/test_arena_lean.py`,
`tests/test_arena_projects.py` and `tests/test_arena_isolation.py`:
**442 passed, 93 skipped in 24.09 seconds**. Native/Docker opt-in tests remained
disabled; skipped cases are not reported as passing.
The same command was repeated after the final concurrent verifier edit:
**442 passed, 93 skipped in 24.53 seconds**. All 13 archived evidence-file
hashes were checked, including byte-for-byte preservation of the generation
plan and report across the two epochs.
