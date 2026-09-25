# Learning how to prompt the running Leanstral server

`jevops.leanstral_prompt_lab` runs bounded, reproducible prompt experiments. It
does not assume that the local model accepts the recommended hosted-model
prompt, that longer context is better, or that JSON compliance implies proof
correctness. Reports are generated from the SQLite ledger, not written by an LLM.

For actual compiler-guided repair versus independent proposals, see the
[bounded repair experiment](LEANSTRAL_REPAIR_LAB.md). It requires isolated native
reference controls before model inference and does not promote or train anything.

## First experiment: context and output contracts

```bash
# Prints a plan; does not call a model or create a run directory.
python -m jevops.leanstral_prompt_lab --output /existing/capped/volume/new-prompt-run

# Explicitly use the existing local Leanstral server. No startup or downloads.
python -m jevops.leanstral_prompt_lab --run --output /existing/capped/volume/new-prompt-run
```

The initial pilot reserves at most **32 requests**, 128 output tokens/request,
45-second socket timeouts, and 32 KiB serialized prompts. It compares:

| Arm | Context | Messages | Output | Temperature |
| --- | --- | --- | --- | --- |
| baseline `plain` | delimited text | user | tactic | 0 |
| `json-context` | JSON | user | tactic | 0 |
| `system-json` | JSON | system + user | request-bound JSON | 0 |
| `system-json-t1` | JSON | system + user | request-bound JSON | 1 |

Each arm gets the same three development tasks twice in randomized block order.
Tasks retrieve a nonce-named hypothesis from Lean-style contexts with distractors
at different sizes/positions. The answer is **not** included in the prompt.
The highest development success count nominates one arm, with the baseline
winning ties. Zero success or incomplete/unknown development evidence abstains.
The nomination is durably frozen before testing it and the baseline on two fresh
nonce contexts twice. A failed confirmation does not trigger another selection.
There is no automatic promotion. A tied baseline needs only 28 total requests.

This is a small **screening experiment**, not a full factorial design or a
significance test. Some arms change multiple factors together, and the initial
size/position conditions are bundled. Follow-up experiments should isolate the
interesting factor with more tasks, matched budgets, fresh seeds and independently
reserved confirmation cases. Nonce holdouts measure retrieval generalization,
not new theorem families. Do not repeatedly tune against the same confirmation
suite or against the Arena's blind canaries.

The report retains exact prompts, outputs, hashes, request IDs, server-reported
token usage, local byte counts, finish reasons, latency, strict-contract status,
normalizations and failure categories. Terminal EOS removal is reported, not
hidden. Truncation is never parsed as a complete candidate. A generic HTTP 400
is not labeled a context-window failure without supporting evidence. Tool calls
are recorded as unsupported, never executed. Neither byte counts nor a successful
small request establishes the server's maximum context length.

Restarting the identical command resumes **only unattempted slots**. Reservations
are committed before requests; interrupted calls consume their reservation and
are never retried. Code/configuration/model-revision changes require a new run
directory. `--model-revision` records an operator-supplied identity; it does not
attest weights. Read-only `/props` and `/v1/models` probes record allowlisted
server claims (context allocation, model filename, model IDs, template hash),
not raw templates or private paths. Visible metadata changes at resume and phase
boundaries stop the run before proceeding; unavailable endpoints remain unknown.
A weight swap or restart preserving those claims is not detectable, so use a new
identity/directory when weights or serving settings change. These metadata GETs
are separate from generation reservations. All calls are sequential. Socket
timeouts are not a total wall-clock deadline.

Use the existing capped volume for output. The runner stops below 32 MiB free;
an injected `storage_guard` can enforce stricter shared-run limits. It never
removes caches/receipts or raises the storage cap. Outputs can contain source code
and diagnostics: keep the run directory private. No secret-bearing environment
dump or remote provider fallback is used.

## Connecting to Arena and the outer loop

### Learning from failures instead of only rerunning fixed templates

`jevops.leanstral_prompt_feedback` recomputes development outcomes from saved raw
responses and produces a frozen successor study. It ignores saved reward fields,
the previous nomination, aggregate summaries and **all confirmation responses**.
Even a confirmation row relabeled as development is excluded using the frozen
case partition. Inconsistent hashes, duplicate slots and incomplete development
coverage prevent an automatic proposal. Saved messages must also equal a fresh
render of the frozen case, repetition and treatment: a matching self-hash alone
does not bind a prompt to the declared experiment. These consistency checks do not
authenticate a saved report.

The first supported automatic intervention is deliberately narrow: when a
successful development arm emits terminal markers, compare it to an otherwise
identical arm using the **observed** marker as an explicit client stop string.
The target is predeclared as `strict_context_accuracy`, requiring the exact
oracle answer and raw output contract, without EOS normalization. Normalized
accuracy remains separately reported. No unsupported hypothesis is invented
when the required evidence is missing. This is not a general-purpose automatic
prompt optimizer, and it does not claim the serving configuration caused a symptom.

A second supported intervention tests `Arm.contract_example=True` for a JSON
arm with observed malformed JSON, wrong fields or request-ID failures. It adds
one fixed, unrelated format example; it never inserts the probe's answer. The
control preserves context, temperature, roles, stop strings and output budget.
Copying the example's request ID fails parsing; copying its tactic fails the
fresh nonce oracle even if the request ID is correct. The parser is unchanged.
The learner considers the stop intervention first when applicable, then observed
literal placeholder copying, then the JSON example; it does not reapply a treatment already present in the selected
development anchor. Missing evidence or exhausted supported hypotheses abstains.
This ordering is a bounded experimental policy, not a learned optimum or a
claim that all JSON errors share one cause. Additional prompt tokens are recorded
as a treatment cost, not hidden by truncating the context.

Literal copying of `the tactic body without by` now motivates a separate
`json_contract_style="descriptive"` treatment. It changes only the schema's
wording; stop strings, examples, oracle and response parser stay fixed. This
hypothesis is proposed only when the placeholder actually occurs in development
output, not merely because JSON seems preferable. Missing responses remain
unknown and block adaptive nomination/successor selection, rather than being
counted as evidence that another prompt is better.

```bash
# The destination's private parent directory must already exist inside the cap.
# This command only generates a NEW JSON manifest; it makes no model calls.
python -m jevops.leanstral_prompt_feedback \
  --report /capped/previous-run/report.json \
  --output /capped/new-run/study.json --seed 29

# Validate/preview; no calls or state writes.
python -m jevops.leanstral_prompt_lab \
  --study /capped/new-run/study.json --output /capped/new-run

# Explicitly execute the frozen comparison, at most 20 generation requests.
python -m jevops.leanstral_prompt_lab --run \
  --study /capped/new-run/study.json --output /capped/new-run
```

Use a fresh seed and fresh confirmation material across the whole experiment
series. The learner rejects reuse of its immediate parent's seed; the caller
still owns the global split registry across other runs. Generated manifests
cannot specify executable code, a different provider, or a replacement verifier.
There is no automatic promotion or modification of the running watcher.

Observable failure features distinguish truncated output, terminal markers,
chat-role leakage, copied context delimiters, fences, malformed JSON, unexpected
fields, foreign request IDs, and a correct tactic followed by extra output.
That last case is **not** evidence that the model selected the wrong hypothesis.

### Matched context capability profiling

`jevops.leanstral_context_profile` adds a reproducible context study without
assuming which serialization Leanstral understands best. Both treatments receive
the **same complete facts**: one as Lean goal-state text, the other as JSON with
propositions, local name/type pairs and a goal. All hypothesis names have the
same shape; the correct binder cannot be found from a special name prefix. The
expected tactic is kept out of every prompt.

The default study crosses 16/128 irrelevant binders with head/middle/tail
placement in **each** split: 12 contexts, two treatments, two repetitions, at
most 48 requests. A one-size study reserves 24 requests. Size counts binders,
not tokens; exact prompt bytes and server-reported prompt tokens are tracked
separately. Facts are matched across positions and representations. Confirmation
uses new nonce names. These are repeated retrieval tasks from matched families,
not 48 independent theorem-proving examples.

The predeclared `confirmation_policy="all_arms"` measures both formats even
when the baseline wins or development has no winner. Pairwise confirmation
counts are generated for each arm against baseline, independently of nomination.
Confirmation still cannot select the next prompt. Existing studies keep their
nominee-only default; every policy reserves its complete design before calls.

Generate a study from an existing development-only anchor, then preview it:

```bash
python -m jevops.leanstral_context_profile \
  --parent-report /capped/previous-run/report.json --seed 83 \
  --distractors 16 128 --output /capped/new-private-run/study.json

python -m jevops.leanstral_prompt_lab \
  --study /capped/new-private-run/study.json --output /capped/new-private-run
# Both commands above make zero model calls. Add --run only for explicit execution.

python -m jevops.leanstral_context_profile \
  --profile-report /capped/completed-run/report.json \
  --output /capped/completed-run/development-profile.json
```

Without `--parent-report`, the builder uses an explicitly provisional
system/user tactic-only baseline, not a claimed optimum. A parent anchor must
have complete, measured development responses and some correct retrievals. Its
confirmation results, saved aggregate rewards and nomination are ignored.
Fresh-seed checks cover the immediate parent; the operator still owns the
experiment-series split/seed registry. This does not protect against all
cross-study reuse or semantic duplication.

The generated development profile separates strict output compliance, normalized
retrieval, well-formed but incorrect answers, truncation and unavailable-response
categories by format/size/position. Observed symptoms can suggest fresh context
or output-budget ablations; they do not identify the cause of a model failure.
Feedback-generated wording/stop studies preserve the structured profile factors
instead of silently substituting the earlier, easier retrieval suite.

Length and position are separate factors because positional retrieval effects
have been demonstrated for other models in
[Lost in the Middle](https://arxiv.org/abs/2307.03172); that motivates a test, not
a claim about this local Leanstral instance. The official
[Leanstral 1.5 settings](https://huggingface.co/mistralai/Leanstral-1.5-119B-A6B)
likewise motivate experiments, not assumptions about a locally served model's
actual allocation, tokenizer or chat template.

Successful retrieval is **not** evidence of general Lean syntax parsing, native
proof validity, maximum reliable context length, an optimal prompt, or improved
Arena score. `context_window_limit` stays null. The existing native Arena judge,
type/axiom checks, token/heartbeat measurements and teacher gates remain required.
No running watcher, budget, checkpoint or prompt policy is changed automatically.

Fresh offline checks, including intentionally wrong responses and transport
failures (not real Leanstral measurements):

```bash
python -m pytest -q --test-seal=off tests/test_leanstral_context_profile.py \
  tests/test_leanstral_prompt_lab.py tests/test_leanstral_prompt_feedback.py \
  tests/test_leanstral.py
```

### Request-ID copying versus client-bound responses

The matched-context pilot's **development** data contained correct tactic fields
with wrong echoed request IDs. `jevops.leanstral_prompt_contracts.request_id_study`
can use that specific symptom to select a diagnostic anchor, ignoring saved
rewards, the previous winner and all confirmation outputs. It abstains on missing
responses or absent evidence. Fresh structured probes retain the same distractor
counts and positions. Both arms run confirmation within a predeclared budget.

The control still requires exactly `{"request_id":"...","tactic":"..."}`.
The experimental `json_tactic` contract requires exactly `{"tactic":"..."}`;
extra fields, including a request ID, are rejected rather than stripped. This is
an explicit change to the response contract, **not** a parser fallback or a way
to turn old failed outputs into passes. The input context and client request ID
remain identical within each pair. Examples adapt to the declared output schema;
all other arm settings and generation limits stay fixed.

`LocalGenerator` snapshots a hash of the exact messages and arm before its
synchronous HTTP request, then binds the raw response hash outside the model's
JSON. The ledger retains the original logical request ID, raw output and this
client record. The experimental contract cannot be scored without a matching
client binding. Wrong, missing or swapped bindings produce unknown results,
not successful tactics. Reporting checks both arms' bindings and recomputes
outcomes from their frozen prompts and raw responses.

These hashes provide trusted-client correlation and consistency checks, **not
cryptographic server attestation** or protection against a hostile producer that
can rewrite both payloads and hashes. Model-authored fields cannot supply the
client binding. Wrong tactics still fail the independent exact-match oracle.

The experimental contract is **retrieval-only**: rendering an Arena case or
using it in `proposal_from_policy` raises before generation. No Arena parser,
native verifier, teacher gate, or watcher default is relaxed. Its eventual use
for proof proposals would require a separate reviewed integration and fresh
native evaluation.

```bash
# Generate a new frozen study from development evidence; zero model calls.
python -m jevops.leanstral_prompt_contracts \
  --report /capped/parent-pilot/report.json --seed 101 \
  --output /capped/new-private-run/study.json

# Preview without execution; --run must be explicitly requested.
python -m jevops.leanstral_prompt_lab \
  --study /capped/new-private-run/study.json --output /capped/new-private-run
```

`comparison_report(report)` generates separate columns for client-bound
responses, strict success under **each declared contract**, and exact tactic
fields ignoring the envelope for diagnosis only. Missing echoed IDs are
inapplicable—not counted as correctly copied—in the treatment. Because schemas
differ, better complete-workflow compliance is not a common-schema improvement
or evidence of better reasoning. Prior scores remain unchanged; neither parsed
retrieval answers nor saved reports can authorize proof promotion or training.

The September 23 **24-request response-contract follow-up** has a
[programmatically generated receipt](papers/completion/lean_refactor_arena/evidence/leanstral-contract-pilot-2026-09-23.json).
Confirmation workflow success was 4/6 for the ID-echo control and 5/6 for
client-bound tactic-only JSON. The treatment still returned one incorrect tactic;
these different-contract results establish neither a proof-quality improvement
nor an Arena score gain. Nothing was promoted or used for training.

```bash
python -m pytest -q --test-seal=off tests/test_leanstral_prompt_contracts.py \
  tests/test_leanstral_prompt_lab.py tests/test_leanstral_prompt_feedback.py \
  tests/test_leanstral_context_profile.py tests/test_leanstral.py
```

### Same-contract identifier-check instruction

`jevops.leanstral_prompt_attention` compares an unchanged development-selected
baseline with a fixed type-match/copy/recheck instruction. Both arms retain the
same exact `json_tactic` contract, examples, context representation, stop strings,
temperature, output allowance and client binding. This is an explicit hypothesis
to test, not an assumption that self-check wording makes answers correct.
The optional `Arm.identifier_check` is disabled by default and accepted only for
validated structured retrieval cases. Existing disabled-arm response bindings
remain compatible with earlier receipts.

The default design uses 16 and 128 irrelevant binders at head/middle/tail in both
splits, with fresh goal and hypothesis names **per cell**. Two repetitions of two
arms use 48 reserved requests; neither repetitions nor nonce changes establish
independent theorem generalization. Development chooses the anchor without
reading prior confirmation outputs. New confirmation is for reporting only.

The audited report regenerates every expected prompt, checks raw hashes and
client bindings, and recomputes the exact oracle. It separates envelope compliance
from wrong-type selections, unknown identifiers and one-character differences.
Near matches remain failures: this is diagnostic labeling, not fuzzy acceptance.
Missing calls remain unknown; saved rewards and nominations cannot change scores.

```bash
# No model calls: generate a fresh comparison from prior development evidence.
python -m jevops.leanstral_prompt_attention \
  --parent-report /capped/contract-pilot/report.json --seed 137 \
  --output /capped/new-run/study.json

# After an explicitly bounded, storage-guarded run, generate both report formats.
python -m jevops.leanstral_prompt_attention \
  --report /capped/new-run/pilot/report.json \
  --output /capped/new-run/pilot/attention-comparison.json \
  --markdown /capped/new-run/pilot/results.md
```

The [official Leanstral 1.5 model card](https://huggingface.co/mistralai/Leanstral-1.5-119B-A6B/blob/main/README.md)
recommends temperature 1.0, with high reasoning effort for complex prompts, and
Lean LSP interaction. These are hypotheses for **separate** local-server and
native-proof experiments, not proof that our quantized deployment benefits from
them. This instruction ablation keeps temperature unchanged at the chosen
baseline setting. It does not enable tools or reasoning flags, change the server
template, or infer available context from the model card's advertised window.
Native proof evaluation remains necessary before deployment or teacher use.

The September 23 [48-request generated receipt](papers/completion/lean_refactor_arena/evidence/leanstral-attention-pilot-2026-09-23.json)
did **not** support enabling this instruction: development success was 9/12
control versus 8/12 treatment; fresh confirmation was 8/12 versus 6/12.
All 48 responses met the JSON envelope, but some selected the wrong hypothesis
or invented/miscopied an identifier. The treatment added 74 median prompt tokens.
The baseline remains unchanged, and `identifier_check` stays experimental/off.
A separate fresh same-contract context-representation or sampling comparison
would test another hypothesis; neither has been run as part of this pilot.

```bash
python -m pytest -q --test-seal=off tests/test_leanstral_prompt_attention.py \
  tests/test_leanstral_prompt_contracts.py tests/test_leanstral_prompt_lab.py
```

### Same-contract context-representation comparison

Use `--experiment context-format` in `jevops.leanstral_prompt_attention` to
compare Lean goal-state text with JSON local-context records. This differs from
the earlier context pilot: **both arms retain the client-bound tactic-only JSON
response contract**, and each size/position/split cell gets fresh nonce material.
The baseline is selected from previous development outputs only, not saved
scores, nomination or confirmation responses. The identifier-check instruction
must be off. Instructions, hypothesis ordering, facts, output allowance,
temperature, examples, stopping and client binding otherwise remain identical.

The reporter rejects compound interventions and a mismatched experiment type.
It recomputes both splits from frozen prompts/raw responses, reports strict
task success separately from envelope compliance, and calculates paired token
cost differences by context size. Missing token telemetry is unknown, not zero;
more verbose contexts are not assumed to be more effective or more efficient.
Existing identifier-check reports keep their original schema and audit behavior.

```bash
# Planning and report generation perform zero model calls.
python -m jevops.leanstral_prompt_attention --experiment context-format \
  --parent-report /capped/identifier-pilot/report.json --seed 173 \
  --output /capped/new-context-run/study.json

python -m jevops.leanstral_prompt_attention --experiment context-format \
  --report /capped/new-context-run/pilot/report.json \
  --output /capped/new-context-run/pilot/context-comparison.json \
  --markdown /capped/new-context-run/pilot/results.md
```

The default crossed design reserves 48 model requests and zero native requests.
Run it only under the existing preparation lock and storage guard, retaining all
caches. Retrieval results cannot authorize an Arena policy change, native proof
admission, autoencoder teacher labels or watcher restart. Repetitions within a
case remain dependent; fresh nonce names are not new theorem families.

The September 23 [48-request generated context-format receipt](papers/completion/lean_refactor_arena/evidence/leanstral-context-format-pilot-2026-09-23.json)
did not support switching to JSON context. Lean-text development/confirmation
success was 11/12 and 8/12; JSON was 8/12 and 7/12. JSON added a median 182 prompt
tokens with 16 distractors and 1,302 with 128, in both splits. Confirmation had
two Lean-only successes, one JSON-only success and nine ties. These are small,
dependent retrieval samples, not proof-quality evidence. The existing baseline,
watcher configuration, training gates and all previous receipts remain unchanged.

### Native context ablations

The September 23 **24-request live matched-context pilot** is recorded in the
[programmatically generated evidence](papers/completion/lean_refactor_arena/evidence/leanstral-context-pilot-2026-09-23.json).
Strict confirmation favored JSON, but the Lean-text failures had correct tactics
and incorrect echoed request IDs. The receipt separates that post-hoc diagnosis
from unchanged strict scores; it establishes no proof-quality improvement.
The raw ledger, generated narrative, development-only profile and integrity
audit are retained at
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/leanstral-context-wttrqj49/pilot/`.

`Arm.context_layers` selects reference proof, proof state, premises, diagnostics
or structural information; an empty tuple supplies statement-only context.
The exact statement, header and version pins remain in every Arena treatment.
Every supplied hint block binds the complete record and reference-source hashes;
missing requested blocks fail before calls instead of silently substituting
another context. Hash binding is not authenticity or proof authority.

```python
from dataclasses import replace
from jevops.leanstral_prompt_lab import Arm, arena_case, context_block
from jevops.leanstral_prompt_feedback import (
    context_study, diagnostic_context, lab_from_study,
)

# Optional: use only matching historical native trials with passing controls.
# A returned block contains bounded diagnostics AND their failed candidate source.
block = diagnostic_context(frozen_record, historical_native_trial)
case = arena_case(frozen_record, context_blocks={"diagnostics": block})

# Alternatively, explicitly bind a captured goal/premise/structure observation:
state = context_block(frozen_record, captured_goal_text, origin="native capture ID")
case = replace(case, context_blocks={**case.context_blocks, "proof_state": state})

# Supply >=3 development and >=2 fresh confirmation cases with required blocks.
# Do not auto-fill these with the benchmark's blind holdouts.
study = context_study(explicit_cases, Arm("anchor", "json", "json", "system_user"),
                      layer="diagnostics", max_native_requests=explicit_native_budget)
lab = lab_from_study(new_output_directory, study, judge=trusted_native_judge,
                     storage_guard=existing_storage_guard)
```

Check for `block is None` before assembling a diagnostic treatment. Missing or
incomplete reference controls produce no diagnostic block; fixtures and
source/pin/receipt mismatches are rejected. Imported history is only a prompt
hint and is never used to label a fresh candidate. `context_study` changes one
context factor at a time and retains the native strict-dual objective. Running
an Arena study without a native judge cannot nominate a proof policy.

The library supports explicitly supplied `Case` and `Arm` objects, including
different context sizes, retrieved lemma signatures, compiler diagnostics,
few-shot examples, and additional temperatures. Keep those inputs version-bound;
changing the case/arm suite changes the plan identity. The text client also now
accepts bounded system/user/assistant messages (no tool execution), although the
initial suite tests only single-user and system/user layouts.

`arena_case(record, split=..., context=...)` binds a prompt to a frozen Arena
problem. Caller-owned records are snapshotted; repeated names, exact statements
or exact sources across development/confirmation are rejected. This is not a
semantic duplicate detector. Supply a genuine family-disjoint partition where
that is required; the runner never auto-selects reserved benchmark holdouts.

For real proof-policy learning, inject `NativeJudge(prepare, identity=...)` into
`PromptLab`, reserve the full `max_native_requests` budget, and supply at least
three development and two confirmation Arena cases. `prepare(record, limit)` is
trusted infrastructure returning fresh, isolated native verifiers and setup
failures. The operator owns the existing preparation lock, immutable project
bindings and storage guard; this hook does not provision environments.

The judge runs the existing balanced Arena trial: reference/candidate, both
branch orders, two repetitions, every pinned version, fresh processes and no
receipt cache. It revalidates dependency contexts and uses the existing
`strict-dual-v1` rule: fewer reference-tokenizer tokens **and** separated lower
heartbeats, preserved type and no axiom expansion. Failed controls or missing
environments are unknown, not negative examples or successful compression.
Prompt-policy confirmation and individual proof admission remain separate.

Without that judge, Arena outputs have `native_verified=null` and no policy can
be selected from their token counts. Injected model/compiler fixtures are labeled
as fixtures. Serialized reports cannot be supplied as native proof authority.

To use a nominated arm as an experimental proposal source:

```python
from jevops.leanstral_prompt_lab import (
    Arm, LocalGenerator, arena_case, proposal_from_policy,
)

# Explicitly choose a frozen arm from a reviewed experiment. The caller reserves
# this request against its existing outer-loop budget before calling.
arm = Arm("json-context", context_format="json")
draft = proposal_from_policy(
    arena_case(frozen_record, context=observed_diagnostics),
    arm,
    generator=LocalGenerator("http://172.17.0.1:8080/v1", 512, 45),
)
# draft is None or an UNVERIFIED Candidate. Feed it through the existing native
# screen/confirmation path, not directly into promotion or autoencoder teachers.
```

This does **not** replace the running watcher controller or authorize Python
edits. Proof-generation prompting, controller JSON, Python patch correctness,
and autoencoder teaching quality need distinct evals. Only newly verified,
scope-eligible proof pairs may enter the existing teacher pipeline; probe answers,
model-reported scores and merely parsed tactics never become training labels.

## Research informs experiments, not presumed capabilities

Mistral's official [Leanstral-2603 model card](https://huggingface.co/mistralai/Leanstral-2603)
and [Leanstral 1.5 model card](https://huggingface.co/mistralai/Leanstral-1.5-119B-A6B)
recommend temperature 1.0 and discuss reasoning effort, large contexts and
tool-assisted workflows. That motivates a temperature arm; it does not identify
the weights, template, tokenizer or context allocation behind our local alias.
The pilot does not test reasoning-effort controls, images, tool execution,
multi-turn repair, Python patches, or 200k-token contexts. Those remain explicit
follow-up experiments, not silently advertised capabilities.

Next useful experiments are matched-context ablations (goal only vs full proof
vs relevant signatures vs fresh diagnostics), a separately budgeted repair turn,
and proof-family-disjoint native evaluation of the best formats. Keep failed
outputs and native diagnostics to form hypotheses; predeclare the next comparison
instead of changing the current experiment after seeing its confirmation results.

## First local pilot: September 23, 2026

The completed 32-call run nominated `system-json` at temperature 0. Development
successes were plain **3/6**, JSON context **5/6**, system+JSON **6/6**, and
system+JSON at temperature 1 **2/6**. Frozen confirmation was system+JSON **4/4**
versus plain **0/4**. Successful answers required the predeclared terminal-EOS
normalization; none of the system+JSON successes met the raw strict contract.
Observed failures included copied context delimiters, extra JSON fields,
continuation into chat-role markers, and output truncation.

The largest server-reported prompt count was **5,606 tokens**. A separate,
post-pilot metadata observation reported `n_ctx=8192`, four slots, and the
filename `Leanstral-1.5-119B-A6B-NVFP4.gguf`. The observation is explicitly not a
precommitted weight identity. Automatic metadata drift checks were added after
this pilot; they were exercised with fixture tests, not retrospectively claimed
for those 32 calls. Neither the reported context allocation nor the successful
probe sizes establishes a maximum reliable reasoning context.

The programmatically generated ledger, full report, metadata observation and
compact summary are retained in
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/leanstral-prompts-kx4wLL/`.
No new Lean proofs were verified, no teachers trained, no watcher policy changed,
and no benchmark-score improvement claimed by this pilot. The nominated format
is a candidate for native Arena evaluation, not a proven optimal proof prompt.

## First feedback-driven successor study

The learner used only that pilot's development responses to propose a terminal
stop-string comparison. Fresh seed 29, identical system+JSON prompts and a
128-output-token budget were used in both arms. The 20-call study completed with
stable visible server metadata at phase boundaries:

| Treatment | Strict development | Strict confirmation | Normalized confirmation |
| --- | --- | --- | --- |
| No explicit stop | 0/6 | 0/4 | 2/4 |
| Observed EOS stop string | 4/6 | 2/4 | 2/4 |

This is evidence of improved **output-boundary compliance**, not improved
retrieval reasoning or proof quality. Wrong JSON envelopes, malformed markers,
chat-role continuation and output truncation persisted. In particular, the
model sometimes generated a malformed marker that did not equal the configured
stop string. The experiment did not silently broaden stopping/normalization
after observing those failures. No speed or statistical-significance claim is
made from the small paired sample.

The generated study, parent-development digest, full report and compact summary
are retained in
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/leanstral-feedback-8DTK0z/`.
The outer watcher, native admission rules, and autoencoder teachers are unchanged.

## Second feedback-driven successor study

Development-only JSON failures from the first successor triggered the
output-example hypothesis. With fresh seed 41, both arms kept the observed stop
string, temperature 0, system+JSON messages and 128-token output budget. Only the
unrelated JSON example differed. All 20 local requests completed; visible server
metadata remained stable at phase boundaries.

| Treatment | Strict development | Strict confirmation |
| --- | --- | --- |
| No format example | 3/6 | 1/4 |
| Unrelated JSON example | 4/6 | 4/4 |

Success requires both the correct nonce hypothesis and the raw JSON contract;
normalized accuracy was identical to strict accuracy in this experiment. Three
confirmation pairs favored the example and one tied. The example cost **57
additional server-reported prompt tokens per request**. The largest observed
prompt was 5,667 tokens. The example arm still had two development request-ID
failures; no response copied the example values. These are descriptive screening
results from two confirmation contexts repeated twice, not four independent
theorems, a significance claim, or a demonstrated speed/proof improvement.

The generated study, raw report, SQLite ledger, summary and read-only native
readiness observation are retained in
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/leanstral-example-6d7DHv/`.
No native requests, training or promotions occurred; caches and watcher
configuration were retained. All 322 targeted tests passed with test seals off.

The existing watcher is alive but gated by `ENVIRONMENT_FAILED`: its saved
`Core.InitsUpdatesComm` reference controls report `reference_target_missing`
on v4.27.0 and v4.29.1 (four failures each), while v4.26.0 controls passed.
This is an evaluator/reference failure, not a negative Leanstral label.
The unchanged watcher budget has 36 native requests remaining; a complete
two-arm, five-case prompt study requires at least 160 reserved native requests
even with one pin per case. Native evaluation needs the reference-control issue
repaired, an explicitly resumed frozen runtime, and a separately authorized
budget. No failed control or budget gate was bypassed.

A subsequent [native verifier investigation](ARENA_NATIVE_VERIFIER.md#preserve-frontend-errors-before-judging-a-proof)
found lost frontend errors masking unavailable sandbox imports. The working-tree
driver now preserves those failures; this does not retroactively validate prior
receipts, repair the import layout, or update the frozen watcher runtime.

The subsequent [exact native import-closure study](ARENA_PREPARATION.md#scope-bound-native-import-closures)
also cannot unblock those controls within the current staging limits: the two
required closures still need 162.7 MB and 143.7 MB of payload, before conservative
allocation overhead. No imports were copied and no prompt, training or score
claim was advanced. Treat this as an environment constraint, not Leanstral's
proof failure or feedback to its prompt learner.

Fresh tests, bypassing opt-out test seals:

```bash
python -m pytest -q --test-seal=off tests/test_leanstral_prompt_lab.py \
  tests/test_leanstral_prompt_feedback.py tests/test_leanstral.py
```
