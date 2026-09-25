# Refactoring template pilot — September 23, 2026

This is an exploratory experiment on the public warm-up problem
`Core.InitsUpdatesComm`, not a held-out comparison or official Arena submission.
It tests the actual running local Leanstral route, not fixture responses. The
existing server reported `leanstral_local`, the filename
`Leanstral-1.5-119B-A6B-NVFP4.gguf`, and an 8,192-token context allocation per
slot. Those are server claims, not weight or hardware attestation.

## Fixed generation design

Eight requests: two per arm, randomized block order with seed 43. All arms use
temperature zero, a 1,024-output-token cap, a 120-second socket timeout, the
same existing local endpoint, and the explicit `<|im_end|>` stop string motivated
by the earlier [output-boundary experiment](LEANSTRAL_PROMPT_LAB.md). Greedy
repetitions are not independent statistical samples, nor guaranteed bit-identical
outputs. No response from this pilot becomes another arm's context.

| Arm | Historical input | Observed output outcomes |
| --- | --- | --- |
| Legacy harness prompt | None | One fenced tactic block; one empty completion |
| Repair, no history | None | Two fenced tactic blocks |
| Repair, failure history | Frozen rejected Core trials | One full theorem with a changed statement; one empty completion |
| Contrastive history | Same failures plus the earlier successful repair | Two empty completions |

The **strict tactic-only result was 0/8 acceptable drafts**. This does not mean
eight Lean rejections: four failures occurred at the client boundary, three
outputs violated the strict fence contract, and one violated the frozen theorem
envelope. The new templates did not establish a gain on this pilot. The two
repair arms isolate history presence; the legacy and contrastive comparisons
change several prompt factors together. Two calls on one previously studied
problem cannot establish a general ranking of templates or model quality.

The compact-history setting retains at most two detailed observations per
example, while preserving every observed version/outcome in the summary. This
keeps both positive and negative examples within the intended context allowance.
Prompt lengths were 3,398 / 5,754 / 15,319 / 14,503 characters in table order.
The four non-empty responses reported 1,044–5,355 prompt tokens. Empty responses
had no retained usage metadata; they are **not** labeled context-overflow errors.

Summed generation-request wall time was 103.2127 seconds, including failures.
The four responses with usage metadata reported **9,611 input and 1,869 output
tokens in total**. These are partial totals, not the complete eight-call usage.
There was no hosted API route; billed cost and electricity cost were not measured.
No server startup, model/dependency downloads, builds, policy promotion, or
teacher training took place.

## Secondary native check

After the primary screen, the three complete fenced blocks were processed with
the existing `run_warmup.extract_generated_tactics` and
`statement_plus_tactics` functions. This is explicitly **post-hoc secondary
analysis**: the strict-contract results above are not rewritten. No theorem
statement was salvaged or substituted, and no tactic repair was performed.
The full-theorem response and empty completions were excluded.

The bodies were inspected as ordinary tactic code, without generated metaprograms
or IO, before trusted-local native execution. That review is not an OS sandbox.
The existing native verifier uses a private temporary working directory and a
minimal environment; this run did not claim Docker isolation or independent
source-execution attestation. Type, target, axiom and dependency checks remained
unchanged.

The fixed secondary schedule reserves 48 requests: unchanged reference plus
three drafts, every required Lean pin (4.26.0, 4.27.0, 4.29.1), both branch orders,
two repetitions. Receipt caching is disabled. The shared preparation lock
serializes native work; temporary files and reports stay in the existing capped
50 GB workspace. The shorter unverified lengths (129, 221 and 209 tokens versus
224) are not scores or verified improvements.

Completed result: **12/12 control checks verified, 36/36 candidate checks
rejected**, with no unavailable/error/timeout rows. This is not yet a clean
test of raw candidate semantics: all three normalized bodies had a common
layout defect. The existing extractor strips leading whitespace from the
first tactic but retains indentation on later lines. Lean executed the initial
`intros` and then reported `unexpected token 'exists'; expected command`.
The experiment reproduced this harness issue; it did **not** fix the legacy
extraction function or rewrite the original receipts.

A separately recorded, post-hoc whitespace diagnostic preserved the exact
contents inside each complete Lean fence, without changing any tactic. It
ran **eight additional native checks on 4.26.0 only**, both branch orders,
one repetition: two controls verified and six candidate checks rejected.
The legacy draft now reaches a real type mismatch: `InitStatesNodup Hinit`
proves `ks'.Nodup`, but the pending goal is `isNotDefined σ₁ ks'`. It had
deleted the needed `InitStatesNotDefined` step. The repair drafts fail at the
model-generated repeated `generalizing` clause. They also contain additional
malformed syntax; that is not silently repaired or credited as valid output.

Thus there are **zero verified improvements**, even when the layout defect is
removed in this diagnostic. The whitespace-preserved drafts were not claimed
to have passed the other two pins; failing one required pin already prevents
all-version admission. No confirmation run or promotion was justified.
Across both runs: **56 native processes, 14 verified controls, 42 rejected
candidate checks**. No extra model calls were made for the diagnostic.

## Artifacts and commands

Private full run directory:

```text
/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/prompt-template-pilot-20260923-TZq7fU
```

It contains the precommitted plan and exact prompts, server metadata, at-most-once
request reservations, raw responses, generation report, secondary normalization
manifest and candidate files. Reservations are saved before requests; restarting
the same generation plan does not retry interrupted or completed slots. Visible
server metadata drift or changed code/history rejects a resume. No automatic
native execution occurs in the generation tool.

Portable copies of the plans, raw generation report, both native reports and
normalization manifest are in
[`evidence/prompt-template-pilot-2026-09-23`](papers/completion/lean_refactor_arena/evidence/prompt-template-pilot-2026-09-23/).
The machine-readable [summary](papers/completion/lean_refactor_arena/evidence/prompt-template-pilot-2026-09-23/summary.json)
records their content hashes, partial usage accounting, native outcomes, and
the still-unfixed harness layout issue. These copies are reports, not new
independent verification events.

Offline plan (no model request or run-directory creation):

```bash
python papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py
```

The executed generation command was:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 \
  TMPDIR=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp \
  python papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py \
  --generate \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --output /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/prompt-template-pilot-20260923-TZq7fU
```

Use a **new** private output directory for a new experiment; resuming that exact
directory does not purchase another eight attempts. The existing
`python -m jevops.arena_trial --run` performs the secondary native measurements
with the three `fenced-slot-{2,3,6}.json` files, `--proposal-cap 0`,
`--repetitions 2 --seed 43 --max-calls 48 --timeout 90`, `projects-strata.json`,
and the isolated prepared Elan home, under `single-build.lock`. It saves
`native-screen.json`; an existing output is never overwritten.

Offline regression command, observed **272 passed in 24.25 seconds**:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=off \
  tests/test_refactor_prompts.py tests/test_prompt_template_pilot.py \
  tests/test_leanstral_prompt_lab.py tests/test_leanstral_prompt_feedback.py \
  tests/test_leanstral.py tests/test_arena_trial.py
```

First fix and independently test layout-preserving extraction; do not silently
retrofit that fix into this pilot's results. Then isolate the output contract (single-user tactic text
versus system-message/request-bound JSON) on fresh, equally budgeted proof
requests. The earlier nonce-context results motivate that hypothesis but do not
prove it will improve refactoring. The successful historical repair is already
visible in one arm: reproducing it would not be a novel discovery or held-out win.
