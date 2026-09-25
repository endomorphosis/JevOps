# Refactoring prompts informed by previous rounds

Seven opt-in templates feed the existing Leanstral warm-up path and can render
structured refactoring messages for **Meta MUSE or local Leanstral**. They draft
untrusted tactic blocks; they do not change the verifier, admission rules,
keep-best selector, provider, endpoint, or official scoring. `legacy` remains
the harness default. No new runtime dependency or model service is required to
render prompts.

## Choose the task

| Template | Useful historical inputs | Prompt emphasis |
| --- | --- | --- |
| `minimize` | Shorter successful drafts and failed deletions | One local edit; check implicit premise uses and induction dependencies |
| `repair` | Exact rejected source with Lean diagnostics | Fix the earliest structural failure, including changed induction-hypothesis arity |
| `contrastive` | Both successful and rejected edits of the same problem | Preserve what worked; avoid the particular failed transformation |
| `performance` | Source lengths and matched raw heartbeat observations | Seek improvements on both axes; do not confuse short syntax with cheap elaboration |
| `portable` | Version-specific outcomes and missing environments | One tactic block for every required Lean/repository pin |
| `coupled-repair` | Small failed edits, arity/goal diagnostics, successful contrasts | Delete **and** repair dependent applications/goal blocks; do not repeat an unchanged failed edit |
| `replan` | Exhausted deletion catalogs, valid alternatives, costs and failures | Propose a coherent alternative outside an unsuccessful fixed action family |

All templates preserve the full frozen statement, header, reference source and
required versions. The common contract requires tactic-only output, prohibits
`sorry`/axioms/statement changes/hidden helper work, and treats historical text
as data. Current-source retrieval names are hints, not proven premises or
guaranteed available declarations. Other problems' proof bodies are not supplied
as examples in this version.

## Preview completely offline

Run from the repository root:

```bash
python -m jevops.refactor_prompts \
  --problem Core.InitsUpdatesComm --template contrastive \
  --history papers/completion/lean_refactor_arena/evidence/native-controlled-core-2026-09-22.json \
  --history papers/completion/lean_refactor_arena/evidence/native-controlled-core-repair-2026-09-22.json
```

Output is JSON containing `prompt` and `manifest`. Add `--text` to print only the
prompt. This command does not probe health, load credentials, contact a model,
compile Lean, update memory, or modify any corpus file. With these two saved
reports, the default budget includes two rejected Core drafts and the subsequent
successful repair, including its smaller local token count. These are **previous
observations**, not a new refactoring result.

The manifest records template/prompt/record content hashes, matched report
hashes, rejected record matches, selected source hashes, omitted examples and
limits. `history_authenticated=false` and `fresh_verification_required=true`
are intentional. A SHA-256 hash checks identity, not truth or provenance.

Library use, including explicit current retrieval hints:

```python
from pathlib import Path
from jevops.refactor_prompts import RefactorPrompts

builder = RefactorPrompts(
    "repair",
    history_files=(Path("my-controlled-trial.json"),),
    max_chars=32000,
    max_examples=4,
    max_observations=8,  # Use 2 for a compact context; per-version summaries remain complete.
)
bundle = builder.build(frozen_record, available_lemmas=("Nat.add_comm",))
# Send bundle.text through an existing authorized generation adapter.
# Keep bundle.manifest with the run; the returned tactic still needs fresh checks.
```

The builder accepts `jevops-arena-controlled-trial/v1` JSON and
`jevops-arena-pareto-selection/v1` wrappers (their actual `screen` and
`confirmation` trials). Pass multiple `--history` files to combine rounds.
It also accepts an explicit `archive-manifest.json` from a native prompt-pilot
triage or deterministic deletion-catalog sweep; see below. Arbitrary summaries,
logs, model-written `theorem_ok` flags and legacy warm-up batch receipts are not
accepted as this richer trial schema. There is no
automatic recursive discovery or ambient memory lookup. Each run explicitly
chooses its historical inputs, so evaluation splits remain operator-controlled.

## Combine recent rounds for Meta MUSE or Leanstral

This completely offline preview combines three different inputs: the full
64-edit native deletion screen, an earlier prompt-pilot archive, and the
successful repair trial. The explicit files define the cutoff, not discovery
order or a guessed timestamp.

```bash
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
python -m jevops.refactor_prompts \
  --problem Core.InitsUpdatesComm --template coupled-repair --provider muse \
  --max-examples 3 --max-observations 2 \
  --history papers/completion/lean_refactor_arena/evidence/deletion-catalog-2026-09-23/archive-manifest.json \
  --history papers/completion/lean_refactor_arena/evidence/prompt-deletion-feedback-2026-09-23/archive-manifest.json \
  --history papers/completion/lean_refactor_arena/evidence/native-controlled-core-repair-2026-09-22.json
```

Change only `--provider muse` to `--provider leanstral_local` for the local
adapter, or use `--template replan` to emphasize a different transformation
family. `--provider` renders `messages` and `manifest`; it does **not** send a
request, choose credentials, probe a server, or compile anything. Without it,
the existing `prompt`/`manifest` output is unchanged. `--text` is for that
single-prompt mode only.

The common instruction/data content is identical across providers. MUSE gets
`developer` + `user` roles; local Leanstral gets `system` + `user`. The final
output reminder follows the quoted input data. Both request a complete tactic
body, with the unchanged reference as the conservative fallback—not an edit
ID, partial patch, reasoning transcript, or JSON envelope. These are supported
adapter profiles, **not empirically optimized or trained model-specific prompts**.

The observed preview above is **18,899 characters** and includes:

- Historical rejection of all 64 catalog sources, with the 128 unrun later-pin
  checks explicitly separate. This compact summary survives `--max-examples 0`.
- A 219-token rejected candidate with an induction-hypothesis arity diagnostic,
  a historically verified 216-token repair, and a 213-token rejected candidate;
  the reference is 224 local tokens. These are prior observations, not new wins.
- Per-source/per-context receipts, complete version-outcome summaries, bounded
  detailed diagnostics, and the prompt pilot's two distinct rejected sources.

`coupled-repair` uses a deterministic, explicitly labelled **heuristic** to
prefer function-expected/goal-stack diagnostics and small edits, reserving a
slot for a positive contrast when available. It does not treat the shortest
broken proof as the best repair seed. Existing five-template selection behavior
is preserved. Under a small character budget even the reserved positive example
can be omitted whole; consult `dropped_examples` rather than assuming it fit.

The [0/64 deletion result](REFACTOR_DELETION_CATALOG_SWEEP.md) is why these modes
allow a coupled repair or alternative full tactic, not forced selection from
that unchanged catalog. The summary remains **historical**, not a current
blacklist or a claim that every possible refactor fails. No existing candidate
admission, verifier, action catalog or keep-best rule was weakened.

### Library and authorized live handoff

```python
from pathlib import Path
from jevops.refactor_prompts import RefactorPrompts

builder = RefactorPrompts(
    "coupled-repair",
    history_files=(Path("selected-round/archive-manifest.json"),),
    max_examples=3, max_observations=2,
)
bundle = builder.build_messages(frozen_record, provider="muse")
# Or provider="leanstral_local". No I/O except the explicit history/template files.
# jevops.muse_lean.refactor_prompt(frozen_record, builder=builder) is a thin alias.
```

Only in an explicitly authorized, budgeted **live** workflow, pass these
messages to the existing router, with explicit model/endpoint configuration:

```python
from jevops import llm_router, muse, leanstral

provider = bundle.manifest["provider"]
adapter = muse if provider == "muse" else leanstral
raw = llm_router.generate_text(
    None, provider=provider, messages=bundle.messages,
    model_name=muse.DEFAULT_MODEL if provider == "muse" else leanstral.MODEL,
    base_url=adapter.BASE_URL, max_new_tokens=1024, timeout=60,
)
trace = llm_router.get_last_generation_trace()
# Keep bundle.manifest, raw, trace (including usage/finish reason) with the round.
# Reject truncation/malformed output; lexical intake is NOT proof admission.
# Every candidate still needs fresh target/type/axiom checks on all required pins.
```

This live snippet was **not run** for the change. It retains the adapters'
endpoint/credential restrictions and adds no fallback, tool calls or automatic
execution. The existing `leanstral_prompt_lab.parse_response` tactic contract
can check the reply envelope; require strict compliance and a non-truncated
successful finish, then apply the existing source intake and native verifier.
Do not use MUSE's permissive toy `extract_tactic` helper to salvage a malformed
refactoring reply. Call/token/spend reservation and verification remain the
calling experiment's responsibility. Character limits do not establish that
the prompt plus output allowance fits either model's token window.

The frozen `run_warmup.py` CLI remains **Leanstral-only**. It automatically
accepts the two new `--prompt-template` choices and archive manifests through
`--prompt-history`; its default `legacy` prompt/provider is unchanged. MUSE
uses the explicit shared-router handoff above, not a disguised warm-up provider
swap. No new service or dependency is installed.

### Archive checks and boundaries

`jevops.refactor_history` reads only fixed, bounded sibling files named by the
supported format: `plan.json` + `sweep.json`, or `plan.json` + `native-plan.json`
+ `native-triage.json`. It checks their manifest hashes/sizes, plan identity,
source/pin matrix, unique sources and labels, duplicate rows and each receipt
through the existing trial validator. Sweep actions are reconstructed from the
recorded line spans and exact original bytes, not today's potentially changed
slicer. Large matrices are validated in bounded trial chunks; all candidates
are validated even when only a few fit the prompt.

Coverage is recomputed from checked row bindings, **not** copied from summary
winner flags. Not-run checks are never observations; timeouts/errors remain
inconclusive. A fully rejected-catalog hint also requires passing reference
controls. Historical successful receipts now require consistent allowed-axiom
reports as well as target/type/process checks. Inconsistent older exports are
rejected before model access rather than quietly accepted as positive examples.

At most eight explicit history inputs, each at most 2 MiB, may be selected. For
archives, each of the two or three allowlisted sibling files also has that bound;
the manifest's other files are not traversed or ingested. Symlinked payloads,
duplicate JSON keys, non-finite values and mismatched file hashes fail closed.
Repeated archives/examples/observations are deduplicated. Record changes remove
both old examples and coverage summaries. The manifest records consumed file
hashes and selected summaries for reproducible cutoffs. It does not authenticate
the archive author: an attacker able to rewrite a report and all its hashes can
still invent history. These hints never authorize a new proof.

## Use in the existing harness

On a prepared host, add these options to the bounded warm-up command from the
[Leanstral guide](LEANSTRAL_INTEGRATION.md):

```bash
python papers/completion/lean_refactor_arena/harness/run_warmup.py \
  --run --name Core.InitsUpdatesComm --network deny \
  --state-root /prepared/track1-lake --elan-home /prepared/elan \
  --max-new-tokens 512 --generate-timeout 120 --compile-timeout 120 \
  --prompt-template contrastive --prompt-max-examples 2 \
  --prompt-history papers/completion/lean_refactor_arena/evidence/native-controlled-core-2026-09-22.json \
  --prompt-history papers/completion/lean_refactor_arena/evidence/native-controlled-core-repair-2026-09-22.json \
  --receipts-dir /owned/new-warmup-receipts
```

Replace the placeholder directories. This is an opt-in **live/native** command,
not a preview; it was not run for this change. `--network deny` concerns the
compiler environment, not the local model HTTP request. Follow the shared
[one-build lock and provisioning limits](ARENA_PREPARATION.md). Do not use
`--synthetic-compile` to claim a real Lean success, or `--no-live` as a warm-up
generation disable switch (that option belongs to the legacy self-check).

History and all selected prompts are validated before health HTTP, compiler
setup or generation. Oversized mandatory input fails rather than truncating the
theorem. Prompt options incompatible with self-check/plan/health-only operations
are rejected. The JSON batch report gains `refactor_prompts` manifests; frozen
per-problem receipt formats are unchanged. Generated drafts still go through
lexical admission, pinned compilation and the existing keep-best path. The
harness uses its current-source lemma hints; the standalone preview has no
retrieval hints unless supplied through the Python API.

## What the history means—and does not mean

- Records must match the **entire frozen record hash**, not merely the theorem
  name. Changed source, statement, header, metadata or pins excludes the old
  trial. This deliberately conservative rule also excludes harmless metadata
  edits; re-export suitable trials rather than silently rebinding receipts.
- Every sample is checked against its candidate source hash, target, version,
  immutable context and reconstructed verification request. Measurement method,
  dependency digest and branch order must match when measurements exist.
  Malformed or mismatched history fails closed, including unused examples.
- Internally consistent receipts are still unauthenticated historical reports.
  `VERIFIED` does not verify a new candidate or a changed installed environment.
  Even identical frozen records can now have different dependency builds.
- Failed tactics are not false theorems; timeouts, errors, missing infrastructure
  and exhausted budgets remain distinct. A receipt can legitimately precede any
  measurement report; it then carries no invented costs or diagnostics.
- Repeated files and identical observations are deduplicated. A request hash
  identifies context/source, not an independent execution. Shown repetitions
  are not votes or a statistical estimate. Every observed pin/outcome remains
  in the coverage summary; missing pins and omitted detailed observations are
  explicit. This is not an all-version success certification.
- Heartbeats are paired candidate/reference raw units within their recorded
  context, method and order. Zero remains zero. Local token counts are labeled
  `arena.reference_tokens`, not official worker-attested metrics. Templates
  compute no score or accepted improvement from these historical hints.
- Historical sources/diagnostics are JSON-quoted data under an explicit common
  contract. Only selected fields reach the prompt; arbitrary winner flags and
  extra metadata do not. This reduces accidental instruction confusion, but is
  **not** a guarantee against model prompt injection. Output checking is still
  the admission boundary.

Default limits: 32,000 characters, four examples, eight detailed observations
per example, two diagnostics per observation (2,000 characters each). At most
eight explicit history files of 2 MiB each are accepted. Larger example bodies
are omitted whole and reported, never silently spliced. `--max-examples 0`
disables examples; zero character budget is invalid. Harness options use the
`--prompt-` prefix. Character bounds are not model-token bounds: choose a lower
limit if the serving model's context window requires it, leaving generation
headroom. No tokenizer/model download is performed to guess that window.
`--max-observations 2` (harness: `--prompt-max-observations 2`) bounds detailed
history rows without dropping their complete per-version outcome summaries.
The supported range is 1–8; the default remains eight.

## Validation and next quality experiment

### Expanded archive and two-provider validation

Observed after this extension: **559 passed in 25.77 seconds** with test seals
disabled. This is a targeted suite, not a whole-repository run. All model
responses/transports in these tests are offline fixtures; no live MUSE or
Leanstral generation, paid request, credential lookup by the prompt builder,
new Lean proof or performance improvement is claimed.

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --test-seal=off \
  tests/test_refactor_prompt_archives.py tests/test_refactor_prompts.py \
  tests/test_muse.py tests/test_leanstral.py \
  tests/test_deletion_feedback_pilot.py tests/test_deletion_id_pilot.py \
  tests/test_deletion_order_pilot.py tests/test_prompt_template_pilot.py \
  tests/test_local_edit_proposals.py tests/test_deletion_catalog_sweep.py \
  tests/test_arena.py tests/test_arena_trial.py tests/test_leanstral_prompt_lab.py \
  tests/test_leanstral_repair_lab.py tests/test_dependency_boundary.py \
  tests/test_harness_loop.py tests/test_kernel_boundary.py
```

The additional tests cover all seven templates over all 15 frozen records for
both message profiles; actual router/client validation using fixture HTTP;
the real saved 64-edit sweep and prompt-pilot archive; combined successful and
failed histories; changed records; deduplication; zero/exact character and
example bounds; forged receipt/axiom/summary flags; duplicate/missing rows;
hash/symlink/JSON corruption; quoted instruction injection; transient outcomes;
and offline CLI previews. Existing warm-up and prompt-pilot regressions pass.

Changed implementation: `refactor_prompts.py` supplies selection/messages and
the existing history validator, `refactor_history.py` converts bounded archives,
`muse_lean.refactor_prompt` is a thin convenience adapter, and two new files in
`jevops/prompts/` hold the editable mode instructions. Warm-up CLI help and this
guide describe the new inputs; its provider and default prompt remain unchanged.

### Original five-template baseline

The first [live refactoring-template pilot](REFACTOR_PROMPT_EXPERIMENTS.md)
records actual outcomes separately from these offline tests.
The [contract follow-up](REFACTOR_CONTRACT_EXPERIMENT.md) independently tests
layout preservation, message roles and request-bound JSON output; it does not
retroactively change the earlier pilot's receipts.

The original offline tests covered the five initial templates over all 15 frozen problems; real saved
failed/repaired/selection-report inputs; binding corruption, malformed JSON and
non-finite costs; missing measurements; duplicate replay; record changes;
zero/exact-boundary budgets; diagnostic truncation; legacy prompt preservation;
and synthetic harness generation with admission rejection. Fixture compilers
and responses are not native Lean proofs or live model evaluations.

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  python -m pytest -q --test-seal=refresh \
  tests/test_refactor_prompts.py tests/test_leanstral.py \
  tests/test_arena_trial.py tests/test_arena_pareto.py \
  tests/test_lean_refactor_corpus.py tests/test_dependency_boundary.py \
  tests/test_harness_loop.py tests/test_kernel_boundary.py
```

Observed on September 23, 2026: **334 passed in 23.29 s**, zero reused test
seals. The standalone `run_warmup.py --offline-self-check` also returned
`ok=true`, `offline_fixtures=true`, `live_health_checked=false`, retained the
deliberate Putnam generation failures, and reported `arena_score=null`.
The offline contrastive preview above emitted a 31,260-character prompt with
three examples: rejected 213/219-token drafts and the historically successful
216-token repair, against the 224-token reference. These lengths use the local
tokenizer and are not a newly measured Arena improvement.

No live prompt-quality improvement is claimed by these tests. The next controlled
experiment should freeze the same historical cutoff and task set for every
template (including `legacy` and new-template/no-history ablations), use the same
model/sampling settings and call/token budgets, and save the manifests. Measure
fresh all-pin validity, tokens and matched heartbeat trials with confirmation,
including failed and unchanged outputs. Measure actual latency/cost only if
observed. Never feed a task's evaluation-round results back into another arm of
that same comparison. Cross-task retrieval, automatic template bandit selection,
live quality evaluation of the new modes/MUSE profiles and broader warm-up-report
conversion remain deferred. Start the next paired experiment with the exact
same history cutoff for all arms, including no-history and legacy controls;
score fresh validity before comparing tokens and matched heartbeat costs.
