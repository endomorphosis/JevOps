# Leanstral message roles and output contracts — September 23, 2026

This follow-up to the [template pilot](REFACTOR_PROMPT_EXPERIMENTS.md) fixes
multiline tactic extraction before making a fresh, matched prompt comparison.
It is exploratory public warm-up work on `Core.InitsUpdatesComm`, not a
held-out evaluation, official score, or policy promotion. Previous reports
and receipts are unchanged.

## Generation results

| Treatment | Format/intake accepted | Other outcomes |
| --- | --- | --- |
| Single user, tactic body | 0/2 | Two output-limit truncations |
| System/user, tactic body | 0/2 | Two output-limit truncations |
| Single user, JSON | 1/2 | One JSON contract mismatch |
| System/user, JSON | 1/2 | One output-limit truncation |

All eight calls returned usage metadata: **10,074 prompt tokens and 5,772
completion tokens**, with summed request wall time **246.4635 seconds**.
No retries, empty completions, fixture responses or alternate providers were
used. The same server-reported model filename, template hash and 8,192-token
per-slot context allocation were observed as in the previous pilot; these are
serving metadata, not independent weight/hardware attestation. Hosted API and
electricity costs were not measured.

Format acceptance is not refactoring success. The single-user JSON response
contains a 225-token draft against the 224-token reference, swaps the two
length hypotheses, and has inconsistent indentation in the original JSON
string: its first tactic is at column zero and subsequent peers are indented.
The fixed parser preserves that model-produced layout rather than inventing a
repair. The system/user JSON response merely copies `the tactic body without by`
from the contract placeholder; its six-token length is not an optimization.
Both retain the frozen theorem statement. Neither is made authoritative by
lexical intake or by fitting the requested JSON envelope.

The 2/4 JSON versus 0/4 tactic-envelope counts on one previously studied problem
do not establish a general model-quality advantage. Five responses consumed
their entire 1,024-token allowance without an admissible final body; increasing
the limit or changing reasoning/serving settings would be a **new** experiment,
not a rescue of these precommitted results.

## Native outcomes and saved evidence

The validity screen completed **five fresh native processes**: three verified
reference controls (one on each required pin) and two rejected drafts on
4.26.0. Draft 0 reports unsolved goals followed by
`unexpected token 'exists'; expected command`; draft 1 reports `unknown tactic`.
Four later candidate/version combinations were explicitly not run after those
failures. There were no native timeout, unavailable or infrastructure-error
receipts. Summed verification-request wall time was 65.9761 seconds, excluding
initial binding/fingerprinting setup.

**Zero all-pin-valid candidates and zero verified improvements.** No performance
confirmation or promotion was warranted. The separate two-process layout
regression is additional harness evidence, not an Arena control or generated
candidate result.

Portable [evidence files](papers/completion/lean_refactor_arena/evidence/prompt-contract-pilot-2026-09-23/)
contain the exact plan/messages, raw generation results, native plan/receipts,
both draft sources and layout regression. The
[machine-readable summary](papers/completion/lean_refactor_arena/evidence/prompt-contract-pilot-2026-09-23/summary.json)
binds those files by SHA-256 and separates model trials from the layout test.
Copies are not independent verification events. The plan ID is
`b5b2b3623672ab0fb9f76efd49fe4f96d83ec9b53709bcfe4119179fff12a35f`.

The next justified experiment would separately test an output contract without
a copyable placeholder and a larger output allowance. This run does not show
that either will improve proofs, and rejected outputs must not be promoted to
positive training examples.

## Layout fix

`jevops.lean.trim_tactic_body` removes surrounding blank lines while preserving
every nonblank multiline line, including its indentation. Single-line results
retain the old trimming behavior. Both `extract_generated_tactics` (used by the
warm-up harness) and the strict prompt-lab parser use this helper. JSON tactic
strings receive the same handling as plain text. Joining may uniformly indent
the whole body; it must not move only the first line to column zero.

This is not syntax repair: internally inconsistent indentation is left intact,
and extraction does not authorize a proof. The strict parser still rejects
fences, truncated responses, mismatched request IDs, and `by` envelopes (now
including newline/tab variants). The legacy extractor continues accepting its
existing fence/assignment envelopes, subject to the unchanged downstream
statement, tactic and native verification boundaries.

A two-process native regression on installed Lean 4.26.0 reproduced the old
failure and verified the fixed fenced round trip for:

```lean
theorem LayoutRegression : True ∧ True := by
  constructor
  · exact True.intro
  · exact True.intro
```

The old first-line stripping produces unsolved goals and
`unexpected token '·'; expected command`. The corrected candidate has preserved
type and no diagnostics. This is a non-Arena harness regression, not a model
refactoring success. Offline tests also round-trip the entire frozen Core
reference without changing its body.

## Precommitted comparison

Four treatments form a 2×2 comparison: single user message versus separate
system/user messages, crossed with tactic-only versus request-bound JSON
output. Context format remains plain in every arm; all receive the same
frozen statement, reference, header, pins and retrieved premise-name hints.
No earlier repair or diagnostic history is supplied. This isolates the two
formatting factors instead of conflating them with history changes.

Two repetitions per treatment are shuffled in blocks with seed 53. Every call
uses the existing local `leanstral_local` route, `Leanstral` model alias,
temperature zero, 1,024 output tokens, 120-second socket timeout and explicit
`<|im_end|>` stop. Total allowance: eight requests / 8,192 output tokens.
Greedy repetitions are not independent statistical samples. Each reservation
is persisted before its call; an interrupted reservation is not retried.
Raw responses, route metadata, exact messages, request IDs and code hashes
remain in the report. Empty/error outputs do not gain invented usage counts.

Generation never executes model text. Native validity triage is a separate
opt-in operation requiring operator review of every exact source hash. It
uses unchanged target/type/axiom/dependency checks, fresh receipts, one control
per required pin, and one attempt per candidate/pin. Pins run in order
4.26.0, 4.27.0, 4.29.1. A failed candidate stops receiving further checks;
remaining pins are explicitly `NOT_RUN_AFTER_NON_SUCCESS`, not failed proofs.
A failed control stops subsequent verification. Maximum allowance: 27 native
requests. Incremental receipts survive interruption; rerunning the reserved
triage is refused, rather than silently repeating work.

This single-reference-first validity screen cannot establish a performance
improvement. Any all-pin-valid shorter draft requires a separate fresh
`jevops.arena_trial` comparison with both branch orders and two repetitions
before a strict dual-improvement claim. No candidate is automatically promoted.

Native work is serialized under the existing preparation lock, with temporary
files/reports inside the capped 50 GB volume. No downloads or builds are needed.
Execution is trusted-local private scratch with a minimal environment, **not
an OS sandbox**; code review is not an isolation claim.

## Commands

Offline plan (no model call):

```bash
python papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py --study contracts
```

Executed generation:

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 \
  TMPDIR=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp \
  python papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py \
  --study contracts --generate \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --output /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/prompt-contract-pilot-20260923-8L2EjP
```

`--triage` replaces `--generate` for reviewed drafts; supply explicit
`--projects`, `--elan-home`, and repeat `--reviewed-source-sha256` for each
unique source. Resume only an unchanged generation plan; use a new directory
for any changed code, prompts, settings, or serving metadata.

Executed native command (the first lock acquisition was busy and did no work;
the command below ran after the shared lock became available):

```bash
pilot_root=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM
pilot_out="$pilot_root/work/prompt-contract-pilot-20260923-8L2EjP"
env JEVOPS_REGISTER_LRA_HOOKS=0 TMPDIR="$pilot_root/work/tmp" \
  python papers/completion/lean_refactor_arena/tools/run_prompt_template_pilot.py \
  --study contracts --triage --preparation-root "$pilot_root" --output "$pilot_out" \
  --projects "$pilot_root/work/projects-strata.json" --elan-home "$pilot_root/work/elan" \
  --reviewed-source-sha256 4e7ce43a0bbc99f783dc68148c5bc20e2e6b042ae6c4f5147a3e1815c13e0636 \
  --reviewed-source-sha256 ef3c5250a13a40f840001d7a7bd90f59d536c496e6d120317ee4ba873496c50d
```

Offline regression command, observed **308 passed in 23.78 seconds**:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=off \
  tests/test_refactor_prompts.py tests/test_prompt_template_pilot.py \
  tests/test_lean_tactic_layout.py tests/test_kernel_boundary.py \
  tests/test_leanstral_prompt_lab.py tests/test_leanstral_prompt_feedback.py \
  tests/test_leanstral.py tests/test_arena_trial.py
```

The separate `run_warmup.py --offline-self-check` also returned `ok: true`,
with `offline_fixtures: true` and `live_health_checked: false`. Its synthetic
compiler outcomes are not native evidence.

Additional admission/corpus/native-adapter boundary regressions:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=off \
  tests/test_lean_admission.py tests/test_lean_refactor_corpus.py \
  tests/test_arena.py tests/test_arena_lean.py tests/test_arena_projects.py \
  tests/test_arena_providers.py tests/test_arena_isolation.py
```

Observed **285 passed, 96 skipped in 3.82 seconds**. Opt-in native/Docker tests
were disabled; skipped tests are not passes. This is targeted regression
coverage, not a claim that the entire repository suite was run.
