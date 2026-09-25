# Bounded deterministic composition pilot

## Direct append-term experiment (2026-09-25)

The opt-in `subset-triple-term` leaf-pilot profile nominates two replacements
using the existing three-leaf matcher: a complete nested `exact` term, and
direct `exact` terms only at the leaves with the existing outer `apply` tree.
Both reuse `List.Subset.app` and `List.subset_append_of_subset_left/right`.
The matcher captures the existing leaf hypothesis identifiers; `‹_›` asks Lean
to discharge each hypothesis's premise from the local context. Neither that
notation nor matching the source layout grants proof authority.

Rule names: `subset_triple_term`, `subset_triple_term_leaves`. Only these two
new rules allow source growth, capped at 16 lexical tokens per matched subtree.
Older reconstruction strategies keep their strict source-shrink gate. The
whole-term/leaf-term candidates have **181/178 tokens** against the 169-token
incumbent, so cannot satisfy the strict-dual objective. This batch explicitly
uses `--selection-objective aggregate-local-v1` to measure whether heartbeat
savings compensate. The strict default and strict incumbent are unchanged.

The pilot's v4 plan freezes the objective even for abstention. Execution
reconstructs and hashes that plan before any work; objective changes or old
v3 plans cannot silently execute under a different criterion. Recapture and
replan for new runs; historical artifacts are retained unchanged. The existing
aggregate selector, reference-normalized formula, no-axiom-growth policy,
two-order screen and fresh fixed-winner confirmation are reused unchanged.
There are 16 screening checks and 18 confirmation checks reserved, no retries
or adaptive batch expansion. This is an exposed one-task hypothesis, not a
trained policy or official score.

The [completed aggregate experiment](papers/completion/lean_refactor_arena/evidence/subset-term-strata-2026-09-25/README.md)
returned **NO_IMPROVEMENT**, with 16/16 native checks verified and no axiom
growth. Whole/leaf terms used 1.62%/1.86% more raw heartbeats than the incumbent,
losing about 2.067/1.657 local aggregate percentage points respectively.
No draft qualified for confirmation. The 169-token incumbent is retained;
660 targeted tests passed with six skips, and the archive audit was consistent.

## Explicit propositional normalization (2026-09-25 follow-up)

The opt-in `subset-triple-normalize` profile reuses the three-leaf matcher and
adds two fixed `simp_all only` scripts. Both include `List.Subset`,
`List.mem_append`, `or_imp`, `true_implies`, `true_or`, `or_true`, `implies_true`,
and `and_self`; the first also includes `forall_and`. The rules are named
`subset_triple_simp_normalized` and `subset_triple_simp_normalized_compact`.
The prior three-arm profile and all existing defaults remain unchanged.

This targets the previous simplification-only failure's unreduced `True`
connectives without invoking `grind`. The tactic names alone do not prove
constructivity or lower cost: the existing native checker and no-axiom-growth
selector must still inspect each result. Bounds, statement preservation,
other-branch preservation, and exact full confirmation reserve are unchanged.

The [fixed Strata follow-up](papers/completion/lean_refactor_arena/evidence/subset-normalize-strata-2026-09-25/README.md)
compares 163/161-token drafts to the 169-token incumbent, reserving 16 screening
plus 18 confirmation checks. It uses the existing prepared pin, no downloads,
models, training, or automatic promotion.

Observed result: **NO_IMPROVEMENT** after all 16 screening checks verified.
Both drafts preserved the original `propext`/`Quot.sound` axiom set but used
30.43%/28.83% more raw heartbeats than the incumbent. No candidate qualified
for the 18-check confirmation reserve; the 169-token incumbent is retained.
The report consistency audit passed; this is one exposed task, not a
corpus-wide result or official score.

## Three-leaf subset reconstruction (2026-09-25)

The opt-in `subset-triple-reconstruct` profile in `arena_leaf_pilot` nominates
three replacements for one exact, already-lifted three-leaf append subtree:

- `subset_triple_simp`: expose `List.Subset` and membership in append, then
  normalize implications/conjunctions with `simp_all only`.
- `subset_triple_grind`: use `grind only [List.Subset, List.mem_append]`.
- `subset_triple_simp_grind`: restricted simplification followed by `grind only []`.

The matcher preserves the case/hypothesis setup, other branches, and statement.
It accepts only the explicitly recognized right-nested layout, with one
left-lifted leaf and a right-lifted pair of left/right leaves. Unsupported
arguments, comments, quoting, tabs/CRLF, continuation lines, and oversized
inputs abstain. It changes only the first complete match. This is bounded
source-pattern proposal generation, not a Lean parser, learned tactic, proof
equivalence theorem, or cost guarantee. In particular, simplification may
leave goals open or close them before a subsequent tactic, and `grind` may
fail or cost more. Every complete draft goes through the unchanged native
checker and strict-dual selector.

The [Strata experiment](papers/completion/lean_refactor_arena/evidence/subset-triple-strata-2026-09-25/README.md)
uses the archived **169-token** strict winner, not the older 185-token source
used in the preceding support experiment. Fresh controls are mandatory; the
saved report supplies a source seed, not reusable proof or cost evidence.
The one-pin three-draft profile reserves 20 screening + 18 fixed-winner
confirmation checks. No retries, automatic promotion, models, or builds.

`jevops.arena_compositions` exports unverified drafts for the existing native
selector. It uses an explicit allowlist, at most eight paths of depth three,
and at most eight distinct outputs. Each path starts from the same original
or explicitly supplied unverified seed;
every step must apply. A partially applied path abstains, rather than silently
being reported as the requested composition. Identical source outputs are
deduplicated. Step source hashes and generator identity are recorded.

Existing Arena transforms are reused. One additional layout heuristic replaces
an adjacent `intro`/`intros` and `exact` of an introduced identifier at a branch
leaf with `repeat intro` followed by `assumption` on its own line. It abstains
on comments, quoted syntax, tabs,
ambiguous indentation, nonleaf uses and unsupported argument syntax. It is not
a Lean parser or semantic equivalence certificate. Lean still checks the whole
proof; neither a smaller token count nor a generated manifest admits a draft.

```bash
python -m jevops.arena_compositions \
  --problem CallElimCorrect.extractedOldExprInVars \
  --path drop_rename_i --path intro_exact_assumption \
  --path drop_rename_i,intro_exact_assumption --cap 3 \
  --output-dir /owned/new-drafts
```

This writes `composition-0.json` through `composition-2.json` and a generated
`manifest.json`. Individual draft files use the selector's exact four-field
schema. No model/Lean calls, training, production promotion or scoring occur.

## Portable rules and historical seeds

The allowlist now includes 19 `port_*` rules from `jevops.folds` through
`jevops.arena_rules`: exact-hypothesis replacement, existential/constructor
packing, simplifier cleanup/hoisting, introduction cleanup, combinator edits,
and qualified-identifier shortening. Existing context-sensitive folds remain
**proposals only**, including removal of an unfold before split or an intro
before `simp_all`. They can be invalid in the current goal and must never be
treated as automatic repairs or proof-preserving transformations.

The adapter passes the reference-compatible counter explicitly to cost-filtered
folds. It does not read legacy token hooks, learned memory, blacklists, or
provider configuration. A shorter qualified name usually still costs one token
and therefore cannot earn fictitious token savings. The `try simp_all` cleanup
now recognizes both `;` and `<;>` continuations; exact-hypothesis replacement
abstains on qualified names and function applications. Inputs with comments,
quoted syntax, tabs, term proofs, or excessive size abstain before these folds.

`--seed seed.json` accepts the selector's four-field draft schema (`name`,
`label`, `source`, `provenance`) with the exact frozen statement. The original
corpus record and reference costs stay unchanged. The manifest records the
seed, base hash/cost, each step's before/after hashes and reference-token counts,
and the adapter/fold source hashes. Neither provenance text nor these hashes
constitute proof evidence. Freeze the complete implementation and inputs for
native experiments as before; the two rule-file hashes are not a transitive
execution attestation.

```bash
python -m jevops.arena_compositions \
  --problem CallElimCorrect.extractedOldExprInVars --seed /owned/seed.json \
  --path port_drop_unfold_before_split \
  --path port_drop_intro_before_simp_all \
  --path port_drop_unfold_before_split,port_drop_intro_before_simp_all \
  --output-dir /owned/new-portable-drafts
```

For externally supplied tactic nominations, `--proposal-file proposal.json`
replaces `--path`. It accepts **only** `record_sha256`, `base_source_sha256`, and
`paths`, using the existing canonical record hash and exact source-byte hash.
It rejects stale bindings and extra fields such as `verified`, `kernel_accepted`,
or claimed rewards. The same rule allowlist, eight-path limit and depth-three
limit apply. This is an offline input boundary for LLM/tactician/hammer
nominations, not a live provider or solver integration. No external package is
imported, no suggested Python is executed, and no nominal solver success becomes
a training label. Only fresh native checks can supply proof evidence; separate
training admission and CE/cosine evaluation still apply.

Freeze the implementation, corpus, project manifest and drafts using
[source snapshots](ARENA_FROZEN_RUNS.md), then pass the three drafts with repeated
`--candidate` arguments to `jevops.arena_pareto`. The pilot predeclares
`strict-dual-v1`, a zero raw-heartbeat noise floor, seed 17, two screening
repetitions and two confirmation repetitions. Its one required version,
two execution orders and four screening arms reserve 16 requests; independent
confirmation of one frozen winner and the original reserves eight more.
There are no retries, adaptive confirmation alternatives or changed acceptance
criteria. An inconclusive result remains inconclusive.

This public warm-up is development data, not an untouched holdout. All three
proposals are generated before native outcomes are inspected. The standalone
arms provide an ablation for their composition, not a claim that compositions
must improve either metric or transfer to other theorems. The separate
diagnostic-guided arity repair remains available for its supported error shape;
this batch does not invent a diagnostic when one is absent.

## Native feedback changed the rule

The first fixed batch used `intros; assumption`. Its two affected drafts failed
all eight scheduled executions: bare `intros` left a `List.Subset` goal unopened.
The original and unused-name-removal arm passed, and fresh confirmation accepted
the latter. The failed batch and frozen source are retained, not rewritten.

Pinned Lean 4.26 source and the [tactic reference](https://lean-lang.org/doc/reference/latest/Tactic-Proofs/Tactic-Reference/)
distinguish bare `intros` (no unfolding) from explicit introductions and
`repeat intro` (which can expose hidden binders). A separate native regression
also rejects `repeat intro; assumption`: the semicolon makes `assumption` part
of the repeated sequence, allowing failed iterations to backtrack. The generator
now emits two equally indented lines. Tests cover both rejected spellings and
the actual generated replacement against a definition hiding the binders.

This is diagnostic-guided engineering with new whole-proof checks, not a claimed
semantic guarantee from a text pattern. A new pilot must compare the repaired
composition against both the original and the previously confirmed incumbent,
with all of them checked afresh. No failed candidate becomes a training target.

## Measured outcome, 2026-09-23

Both experiments used frozen source/input copies, the required Lean 4.26 pin,
balanced execution orders, two repetitions, disabled receipt caches and the
unchanged strict-dual selector. Both snapshots verified unchanged afterward.
Reports, draft manifests, snapshot manifests and compact audits are generated
artifacts, not model-authored receipts:

- [First experiment](papers/completion/lean_refactor_arena/evidence/native-composition-pilot-2026-09-23/summary.md):
  24 native requests. Eight invalid intro/exact draft checks remain recorded as
  rejections. The selected name-removal draft received fresh confirmation:
  **222 → 213 proof tokens**, with approximately **0.0594–0.0595% fewer raw
  heartbeats** in the two execution orders. This small local effect is not a
  statistical or wall-time speedup claim.
- [Repaired experiment](papers/completion/lean_refactor_arena/evidence/native-composition-repair-2026-09-23/summary.md):
  all 12 screening requests verified. The repaired composition has **211 tokens**
  but costs **431 more raw heartbeat units** than the freshly rechecked 213-token
  incumbent in each order (approximately **0.0165% more**). Status is
  `NO_IMPROVEMENT`; confirmation was not started. The verified incumbent remains
  selected, while both 213 and 211 remain on the observed Pareto frontier.

The second result improves both costs over the original, but not both over the
incumbent; the precommitted incremental rule therefore does not promote it.
Neither experiment updates production proofs or trains the autoencoder. This is
one public warm-up problem, not a new global high score or holdout evaluation.
Regression tests preserve both distinctions: invalid-but-shorter cannot win,
and valid-but-more-expensive cannot win the strict-dual objective.

The targeted frozen suite passed 485 tests with 85 native opt-in skips. The
separate explicit native regression run passed all 38 tests in that module,
including its three actual native cases. Subsequent report-bookkeeping tests do
not add fresh native evidence. The next useful search step is eliminating the
repaired proof's introduction/search overhead, while retaining the same gates.

## Historical seed recovery, 2026-09-23

The `random-best-CallElimCorrect.extractedOldExprInVars-260.lean` body from
`lift_coding` commit `680c83db61c747d409f066750e3d753099008a52` uses the legacy
body-only punctuation counter in its filename. It measures **185 tokens** with
the reference-compatible counter (including `by`). The original measures
322 legacy / 222 reference tokens; the recent incumbent is 313 legacy / 213
reference tokens. Historical filenames must not be compared directly to new
costs or treated as proof evidence.

The [fresh recovery experiment](papers/completion/lean_refactor_arena/evidence/native-historical-confirm-2026-09-23/summary.md)
used the unchanged strict-dual protocol, the required Strata/Lean 4.26 pin,
both orders, two repetitions per phase, and 24 fresh native processes. All
passed; the seed was selected and independently confirmed at **185 tokens**,
with approximately **10.8% lower raw heartbeat cost than the 213-token
incumbent**. The source bundle remained unchanged. This recovers an existing
historical result; it is not a newly discovered global record, official score,
wall-time guarantee or unseen holdout result.

The generated [four-field seed](papers/completion/lean_refactor_arena/evidence/native-historical-confirm-2026-09-23/historical-seed.json)
can be passed directly to `--seed` or to the selector's `--incumbent`. It remains
untrusted input that needs fresh checking in each new selection context. A
generated [inventory](papers/completion/lean_refactor_arena/evidence/native-historical-confirm-2026-09-23/recovery.json)
recounts all 25 historical variants at that commit but grants none of them
verification authority. Only the selected 185-token variant participated in
the recovery experiment. No production state or model weights were updated.

The [portable follow-up](papers/completion/lean_refactor_arena/evidence/native-portable-pilot-2026-09-23/summary.md)
then froze three drafts from that seed: removing the unfold before split
(183 tokens), removing introductions before `simp_all` (176), and composing
both (174). All 12 draft executions were rejected; the eight original/incumbent
executions passed. Removing the unfold prevents `split` from exposing the
conditional; removing the introductions leaves subset goals unsolved. Status
is `NO_IMPROVEMENT`, with the verified 185-token incumbent retained and no
confirmation or training of the rejected drafts. These failures are specific
to this proof/context, not evidence for globally blacklisting either rule.

Five separately opted-in native stdlib regression cases passed for generated
portable edits, including the repaired `<;> try simp_all` pattern. Both benchmark
source bundles verified unchanged afterward, and both report-consistency audits
passed. Audits and saved-report regression tests themselves execute no Lean and
grant no new proof authority. The next useful extension is goal-aware local
edits or reconstructible solver proposals, rather than assuming textual
redundancy implies semantic redundancy.

## Terminal intro/simplification hypotheses

Two additional allowlisted paths, `intro_simp_grind_first` and
`intro_simp_grind_all`, nominate replacement of adjacent terminal `intro` and
`simp_all` lines with `grind`. The existing source-bound proposal interface can
nominate these paths without supplying executable Python or reward claims.
They are bounded layout heuristics, not equivalence rules. They reject named
introductions, mismatched indentation, intervening tactics, nonterminal blocks,
comments/quotes, term proofs and oversized inputs. The statement and untouched
branches stay byte-identical; whole-proof checking remains mandatory.

This directly tests an alternative to the failed introduction-deletion edit.
It does **not** assume `grind` can solve these goals or use fewer heartbeats.
First-only and all-leaves are separate hypotheses, deduplicated when identical.
Existing paths and their default behavior are unchanged.

[arena_leaf_pilot.py](jevops/arena_leaf_pilot.py) freezes these two paths against
an explicit four-field incumbent draft. With the historical 185-token Arena
seed it nominates 184 and 176 tokens; these are source lengths, not accepted
scores. The original remains 222 tokens. Its fixed selector requires strict
token and heartbeat improvements over both original and incumbent, both
elaboration orders, two screening repetitions and three fresh confirmation
repetitions. Separation must exceed observed variation and a predeclared
100-raw-heartbeat noise floor. No candidate switching or retries after
confirmation failure, and no adaptive batch expansion, are allowed.

Plan-only usage performs no native verification:

```bash
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m jevops.arena_leaf_pilot \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent papers/completion/lean_refactor_arena/evidence/native-historical-confirm-2026-09-23/historical-seed.json
```

Execution additionally requires `--execute`, the exact `--max-processes` ceiling,
a verified read-only source snapshot (`--snapshot-manifest-sha256`), frozen
`--projects` and `--incumbent` inputs inside it, `--preparation-root`,
`--elan-home`, and a new `--output` directory under the capped volume. `TMPDIR`
must also be inside that volume. It holds the existing exclusive preparation
lock and stops at the storage reserve; no caches are removed. Only prepared
pins are used, with no builds, downloads or model calls. For this one-pin Arena
task the ceiling is 34 processes: 16 screening plus 18 reserved confirmation.

Reports, reservations, source-snapshot checks and summaries are programmatic.
This runner exercises the shared strict selector on actual Arena tactic
candidates. It does not pretend that multi-step tactics came from the distinct
one-lemma knowledge-materialization bridge. Training, proof promotion, the
watcher, and any claim of protected-canary generalization remain disabled.

### Measured leaf-replacement outcome, 2026-09-24

The [generated Arena report](papers/completion/lean_refactor_arena/evidence/native-leaf-replacement-2026-09-24/summary.md)
records `NO_IMPROVEMENT`: all eight original/incumbent samples verified, while
all eight candidate samples were rejected with `candidate_errors`. Exactly 16
native processes ran; no confirmation was selected, no new score was admitted,
and the freshly checked 185-token incumbent was retained. Neither the 184-token
nor 176-token draft receives a reward or a training-target label.

Lean recognized and executed `grind`; the diagnostics show unresolved
subset-of-append obligations such as `xs.Subset (xs ++ ys)`. These are tactic
failures, not timeouts, missing dependencies or evidence that the theorem is
false. They suggest testing goal-aware subset normalization or retrieved
subset/append lemmas under a **new** frozen protocol; this experiment does not
establish that either proposed remedy succeeds. The larger replacement has
multiple failing leaves. A failure here does not globally blacklist `grind`.

The exact receipt/diagnostic data are retained in the
[native report](papers/completion/lean_refactor_arena/evidence/native-leaf-replacement-2026-09-24/report.json).
The [consistency audit](papers/completion/lean_refactor_arena/evidence/native-leaf-replacement-2026-09-24/audit/summary.md)
passed without granting new verification authority. The frozen source snapshot
verified unchanged before and after execution; all caches remain retained under
the unchanged 50,000,000,000-byte allowance. The
[targeted regression suite](papers/completion/lean_refactor_arena/evidence/native-leaf-replacement-2026-09-24/regression.xml)
passed 412 tests with three opt-in native tests skipped. No model calls,
training, watcher restart, project builds, downloads or proof promotion occurred.

## Constructive subset/append follow-up

The opt-in `subset-append` profile uses two new source-bound rules:
`subset_trans_append_left` and `subset_trans_append_right`. Each replaces one
supported terminal transitivity block with
`apply List.subset_append_of_subset_left` or its right-hand counterpart. It
preserves the existing `apply <hypothesis>` / `assumption` discharge and removes
only the now-replaced `intro` / `simp_all` inclusion proof. The explicit list
argument is left for Lean's unification, not guessed in Python.

Both lemmas are present in the pinned Lean 4.26 source,
`Init/Data/List/Sublist.lean`, and are constructive compositions of subset and
append membership proofs. This is **manual, diagnostic-guided library reuse**,
not blind retrieval, a new lemma, a learned rewrite or generalization evidence.
The source matcher does not know the goal's list arguments or certify a
direction. It accepts only exact bounded layout, a single hypothesis identifier,
and terminal discharge blocks. Unsupported syntax abstains. Fresh native
checking decides whether a nomination is applicable and audits its axioms.

This profile freezes three paths: left at the first matching block, right at
that block, and left-then-right at the first two matching blocks. The historical
185-token incumbent yields nominations of 183, 183 and 181 lexical proof-body
tokens respectively. The wrong-direction hypothesis remains in the experiment;
no failure is silently converted to a successful fallback. The original
reference stays 222 tokens. Qualified identifiers retain the existing tokenizer's
one-token convention; this does not measure bytes or transitive proof size.

Use the same pilot command with `--profile subset-append`. On this one-pin task,
the frozen ceiling is 38 processes: 20 screening and 18 reserved for fresh
fixed-winner confirmation. The strict-dual objective, 100-raw-heartbeat noise
floor, all-pin/order coverage, source snapshot, exclusive preparation lock,
storage cap and no-training/no-promotion rules are unchanged. The old default
remains `intro-simp-grind`; old receipts and snapshots are not rewritten.

### Confirmed subset/append result, 2026-09-24

The [generated report](papers/completion/lean_refactor_arena/evidence/native-subset-append-2026-09-24/summary.md)
records `CONFIRMED_LOCAL_IMPROVEMENT` for the left-then-right composition:
**185 → 181 lexical proof-body tokens**, with approximately **19.64% fewer raw
heartbeats than the incumbent in each elaboration order**, based on the three
fresh confirmation repetitions. The unchanged original remains 222 tokens.
This is an incremental result on this exposed Arena task, not a full-15 score,
an official organizer score, a proof of minimum length, or learned compression.

All 38 planned native processes completed: 20 screening and 18 confirmation.
The wrong-direction first-block candidate was rejected in all four screening
checks; the other 34 checks verified. The left-only 183-token candidate was
valid, but the selector froze the 181-token composition before confirmation.
The selected proof preserved the statement and the reference/incumbent axiom
set (`Quot.sound`, `propext`); it introduced no additional axioms. Verifier,
tokenizer, imports and the production proof were not modified.

The result also illustrates why a failing rule should not be globally
blacklisted: applying the right-hand lemma to the **first** block failed, while
the same rule at the **second remaining** block succeeded in the composition.
Any future rule-learning examples must retain the source/goal context and edit
sequence. No automatic training admission is enabled by this result.

The [generated four-field draft](papers/completion/lean_refactor_arena/evidence/native-subset-append-2026-09-24/seed/composition-0.json)
was regenerated with the existing composition tool and its complete source
was checked equal to the confirmed recommendation. Its local label is
`composition-0` because that export contains one path; the experiment's selected
label was `composition-2`. It is a nomination for subsequent runs, **not an
admission cache**: pass it as an incumbent only with new native checks.

The [consistency audit](papers/completion/lean_refactor_arena/evidence/native-subset-append-2026-09-24/audit/summary.md)
passed, and the frozen implementation/input snapshot verified unchanged before
and after execution. The [regression suite](papers/completion/lean_refactor_arena/evidence/native-subset-append-2026-09-24/regression.xml)
passed 457 tests with three opt-in native skips. All caches and failed evidence
were retained under the unchanged storage allowance. No model call, training,
watcher restart, source promotion, build or download was performed.

### Reusing a winner as the next incumbent

Pilot schema v3 separates the saved nomination's label from its comparison
role. The complete input nomination remains in `plan.incumbent`; the selector
uses `incumbent` for that same source and provenance, or shares the original
`control` only when the sources are byte-identical. New arms retain their
`composition-N` labels. This fixes collisions when a one-path exported winner
(`composition-0`) seeds another batch. Renaming conveys no verification or
training authority, and existing v2 receipts/snapshots remain untouched.

With the saved 181-token nomination, the same frozen `subset-append` profile
targets the next matching blocks and proposes 179, 179 and 177 tokens. These
are unverified proposals until a new native trial completes. The reference
remains 222, the comparison incumbent is now 181 (not the older 185), and the
maximum reservation stays 38 fresh processes. Regression tests check repeated
seeding, reserved/colliding labels, exact source/provenance preservation, and
agreement between planning and execution.

### Confirmed second subset/append round, 2026-09-24

The [second-round generated report](papers/completion/lean_refactor_arena/evidence/native-subset-append-round2-2026-09-24/summary.md)
records another `CONFIRMED_LOCAL_IMPROVEMENT`: **181 → 177 lexical proof-body
tokens**, with approximately **7.17% fewer raw heartbeats** than the 181-token
incumbent in each elaboration order. The original reference remains 222 tokens.
This round changes only the two `quant`-case transitivity blocks using the
existing left-then-right path; no new rewrite rule or inferred proof authority
was needed. The comparison denominator is the new incumbent, not the older
185-token proof.

All 38 native processes completed. The right-only 179-token candidate failed
all four screening checks; the left-only 179-token candidate and 177-token
composition passed. The selector froze the composition before 18 new
confirmation checks, all of which verified. Statement and axiom set remained
unchanged (`Quot.sound`, `propext`). The before/after source snapshot matched,
the [report audit](papers/completion/lean_refactor_arena/evidence/native-subset-append-round2-2026-09-24/audit/summary.md)
passed all 39 consistency checks, and [regression tests](papers/completion/lean_refactor_arena/evidence/native-subset-append-round2-2026-09-24/regression.xml)
passed 464 tests with three opt-in native skips (test seals disabled).

The [177-token nomination](papers/completion/lean_refactor_arena/evidence/native-subset-append-round2-2026-09-24/seed/composition-0.json)
was regenerated from the frozen source/input snapshot and checked byte-equal
to the selected recommendation. It still requires fresh native checks when
reused. All caches and failed evidence were retained. This is one exposed
Arena task under its single declared Lean 4.26 pin, not an all-15 benchmark,
official score, unseen canary result or training gain. No model calls,
training, watcher changes, production proof edits, builds or downloads occurred.

### Nested append profile

The opt-in `subset-append-nested` profile freezes five source-bound paths:
left, right, left-right, left-left, and left-left-right. It reuses the existing
two rewrite rules and their depth-three bound; it does not infer directions
or certify proposals from the source layout. This batch tests whether the
next three nested `ite` blocks need a different direction sequence than the
two-block `app` and `quant` cases. The earlier profiles remain unchanged.

Starting from the saved 177-token nomination, the five drafts have 175, 175,
173, 173 and 171 lexical proof-body tokens. Only `ite` blocks are changed;
the theorem statement and other cases are preserved byte-for-byte. These
are unverified nominations until new native checks finish, not cached gains.
On this one-pin task the full reservation is 46 processes: 28 screening plus
18 for a fixed winner's fresh confirmation. Both elaboration orders, the
strict-dual gate, 100-raw-heartbeat noise floor, original 222-token reference,
177-token incumbent, axiom checks and storage/cache policy remain unchanged.
No outcome from a partial or changed batch can authorize confirmation.

### Confirmed nested-profile result, 2026-09-24

The [generated nested-profile report](papers/completion/lean_refactor_arena/evidence/native-subset-append-nested-2026-09-24/summary.md)
records `CONFIRMED_LOCAL_IMPROVEMENT` for the **single left-hand rewrite**:
**177 → 175 lexical proof-body tokens**, with approximately **6.22% fewer raw
heartbeats** than the incumbent in each elaboration order. The 222-token
original remains a separate control. All 46 reserved native processes ran:
28 screening checks and 18 fresh fixed-winner confirmation checks. All
confirmation checks passed with the unchanged axiom set (`Quot.sound`,
`propext`) and statement. The source snapshot was unchanged before/after.

The four other candidates failed every screening check, including the
171-token left-left-right composition. Their 16 rejections remain in the
report; none receives improvement credit. The native diagnostics for that
composition show `tih` being applied to a goal targeting `getVars c`, and
`eih` to a goal targeting `getVars t ++ getVars e`. These are real target
mismatches, not missing theorem declarations or tokenizer discrepancies.

The local `List.Subset.app` splits the source append while preserving the
whole target. Consequently, changing successive textual blocks is not the
same as descending through the target's append tree. A **future, unverified
hypothesis** is to lift the shared inner proof into the outer right-hand
target once, then split that smaller target into its left/right branches.
That requires a new structural proposal and a separately frozen experiment;
this run does not establish its correctness or savings. Do not globally
blacklist these lemmas or admit the failed compositions as training targets.

The [consistency audit](papers/completion/lean_refactor_arena/evidence/native-subset-append-nested-2026-09-24/audit/summary.md)
passed 39 checks, and [regression tests](papers/completion/lean_refactor_arena/evidence/native-subset-append-nested-2026-09-24/regression.xml)
passed 468 tests with three opt-in native skips and test seals disabled.
The [175-token seed](papers/completion/lean_refactor_arena/evidence/native-subset-append-nested-2026-09-24/seed/composition-0.json)
was generated using the frozen implementation and input, then checked
byte-equal to the recommendation. It is still only a nomination for future
fresh checks. All caches and failed evidence were retained. This remains
one exposed task on its single declared Lean 4.26 pin, not an all-15 score,
unseen-canary result or learned compression. No model calls, training,
watcher changes, production proof edits, builds or downloads occurred.

### Shared-target pair proposal

The opt-in `subset-append-shared-target` profile implements the nested-target
hypothesis as two new bounded proposal rules, `subset_pair_target_left` and
`subset_pair_target_right`. They recognize a terminal `List.Subset.app` with
exactly two supported transitivity leaves. A shared outer append-lifting
application precedes the split; its children use left/right lifts while
keeping both existing hypothesis applications and `assumption` discharges.
The extra shared application is charged to the candidate's token count.

This remains a conservative source/layout matcher, not goal inference or
a general Lean AST transformation. It requires adjacent, precisely indented
branches and rejects comments, quotations, tabs, extra children, continuation
tactics and unsupported hypothesis expressions. Both outer directions are
unverified nominations; only a fresh whole-proof kernel check can establish
the selected target shape and theorem compatibility.

Starting from the saved 175-token incumbent, the profile freezes left and
right shared-target candidates at 173 tokens, plus the right-target rule
followed by the two existing `eq`-case leaf rewrites at 169. The paths are
chosen before native execution; old profiles and evidence are not changed.
The original stays 222 tokens, and the current comparison denominator stays
175. The reservation is 38 native processes (20 screening, 18 fixed-winner
confirmation), with the existing strict-dual, axiom, source-snapshot and
storage gates unchanged. No cached admission, training or promotion is enabled.

### Confirmed shared-target result, 2026-09-24

The [generated shared-target report](papers/completion/lean_refactor_arena/evidence/native-subset-shared-target-2026-09-24/summary.md)
records `CONFIRMED_LOCAL_IMPROVEMENT`: **175 → 169 lexical proof-body tokens**,
with approximately **21.04% fewer raw heartbeats** than the current incumbent
in each elaboration order. The original remains 222 tokens. The selected
composition combines the right shared-target repair in `ite` with the two
existing leaf rewrites in `eq`; the other cases are unchanged.

All 38 native processes completed. The left-target alternative was rejected
in all four screening checks. The right-target-only 173-token repair passed,
as did the 169-token composition. The selector fixed the latter before all
18 new confirmation checks, which passed with the same statement and axiom
set (`Quot.sound`, `propext`) as both controls. The added target-lifting
application is included in the token count; no new helper declaration,
tokenizer change or additional axiom supplied the savings.

This supports the specific shared-target hypothesis that failed when the
previous batch treated the inner branches independently. It does not prove
that the matcher handles arbitrary nested Lean syntax or that a model has
learned the rule. The wrong direction and earlier failed compositions remain
negative evidence; no automatic training admission or global blacklist is
created from these results.

The [report audit](papers/completion/lean_refactor_arena/evidence/native-subset-shared-target-2026-09-24/audit/summary.md)
passed 39 consistency checks, and the frozen source/input snapshot verified
unchanged before and after execution. [Regression tests](papers/completion/lean_refactor_arena/evidence/native-subset-shared-target-2026-09-24/regression.xml)
passed 544 tests with three opt-in native skips and test seals disabled.
The [169-token nomination](papers/completion/lean_refactor_arena/evidence/native-subset-shared-target-2026-09-24/seed/composition-0.json)
was regenerated from the frozen implementation/seed and checked byte-equal
to the recommendation. Its one-path export label is `composition-0`; the
selected experimental arm was `composition-2`. Reuse requires fresh checks.
All caches and failed evidence were retained under the fixed storage cap.
This is one exposed Arena task on its single declared Lean 4.26 pin, not an
all-15 score, unseen-canary result or training gain. No model calls, training,
watcher changes, production proof edits, builds or downloads occurred.

### Append-pair simplifier ablation

The opt-in `subset-append-simp` profile nominates `simp_all [List.Subset]`
or `simp_all [List.Subset, or_imp]` for a precisely matched append proof pair.
It tests first-pair and all-pair replacement independently, giving a fixed
two-by-two batch rather than assuming a simplifier will succeed or be cheaper.
`List.Subset` exposes an implicit membership binder in the pinned Lean 4.26
definition; `or_imp` is an explicit proposal for splitting a disjunctive premise.

Only a terminal `List.Subset.app` with adjacent left/right append-lifting
children and supported `apply <hypothesis>` / `assumption` discharges matches.
The conservative matcher rejects unsupported syntax and continuation tactics.
All-pair replacement uses non-overlapping matches from the original input;
it does not recursively expand its own output. The existing shared target
lift and unmatched proof cases remain intact. These are unverified tactic
nominations, not an AST equivalence claim or successful training examples.

From the 169-token seed, first/all unfolding-only proposals have 159/123
lexical proof-body tokens; first/all proposals also using `or_imp` have
161/131. None is an improvement until fresh native admission and cost checks
complete. The original stays 222 tokens and the current incumbent stays 169.
The reservation is 42 native processes: 24 screening, plus 18 fixed-winner
confirmation if a candidate qualifies. Strict improvement in both tokens
and heartbeats, the 100-raw-heartbeat noise floor, statement/axiom checks,
source snapshots, retained caches and the fixed storage cap are unchanged.

### Pair-simplifier result: no strict-dual improvement, 2026-09-24

The [generated report](papers/completion/lean_refactor_arena/evidence/native-subset-pair-simp-2026-09-24/summary.md)
records `NO_IMPROVEMENT`. The **169-token incumbent is retained**, with all
four of its fresh screening checks verified. All 24 screening processes ran;
no candidate qualified for the 18-process confirmation reserve, so those
processes were not launched. No new winner/seed was exported.

The 161-token first-pair `simp_all [List.Subset, or_imp]` candidate passed
all four checks with the unchanged statement and axiom set (`Quot.sound`,
`propext`), but required approximately **33.99% more raw heartbeats** than
the current incumbent in each elaboration order. It is an observed token/
heartbeat trade-off on the discovery frontier, not a strict-dual improvement.
It still beats the original reference on both metrics; comparing only to
that older baseline would have hidden the regression from the incumbent.

The 159/123-token unfolding-only candidates and the 131-token all-pair
`or_imp` candidate failed every check (12 rejections total). Native diagnostics
show unsolved disjunctive membership implications without `or_imp`. With
`or_imp`, the all-pair version still leaves a conjunction of subset goals
in the inner `ite` block. Thus success at the first pair does not authorize
blanket replacement; even valid shorter output can make elaboration worse.
None of these candidates is admitted as a training target or new best score.

The [audit](papers/completion/lean_refactor_arena/evidence/native-subset-pair-simp-2026-09-24/audit/summary.md)
passed all 23 consistency checks, and the frozen source/input snapshot was
unchanged before/after execution. [Regression tests](papers/completion/lean_refactor_arena/evidence/native-subset-pair-simp-2026-09-24/regression.xml)
passed 616 tests with three opt-in native skips and test seals disabled.
All caches and failed evidence were retained. No model calls, training,
watcher changes, production proof edits, builds or downloads occurred.

A next hypothesis is explicit target normalization and a smaller, named
simplification set instead of broad `simp_all`. It needs its own frozen
experiment: this round provides neither correctness nor cost evidence for
that repair. The exposed-task and single-declared-pin limitations still apply.
