# Compiler-gated logic reductions

The router now has a dedicated, bounded formal-logic search branch. This is
an extensible collection of reductions, **not** a complete decision procedure
for Lean, a proof of global shortest length, or a replacement for Lean's kernel.
Arbitrary theorem proving and globally optimal proof minimization cannot be
covered by an exhaustive finite tactic list.

The catalog has since expanded to 28 families, with bounded propositional
equality saturation, finite Houdini inference, hierarchical proof slicing and
opt-in transitive axiom audits. See [the research and implementation report](KERNEL_REFACTORING_RESEARCH.md)
for current coverage and the distinction between arena-span admission and a
strict kernel-only axiom policy. Earlier experiment numbers below are historical;
the expanded operation vocabulary requires its own CE baseline.

## What is implemented

| Family | Implementation | Boundary |
| --- | --- | --- |
| Propositional algebra | Typed AST; constants, double negation, implication elimination, De Morgan, AC/idempotence, complements, absorption, NNF | Bare proposition identifiers and classical truth semantics |
| K-map minimization | Gray-code K-map cells; Quine–McCluskey prime implicants, bounded exact minimum cover, DNF and CNF | Minimum terms, then literals; not minimum Lean tokens |
| Decision diagrams | Reduced ordered BDDs, Shannon decomposition, irrelevant-variable detection | Fixed sorted variable order; no claim of globally smallest BDD |
| Invariant reduction | Implied literals, equal/opposite atoms, sequential redundant-conjunct elimination | Explicit Boolean constraints; inconsistent constraints are marked vacuous |
| Inductive invariants | Separate initiation and transition-preservation checks with counterexamples | Explicit finite Boolean transition system, not arbitrary Lean programs |
| Quantifiers | Distribution/witness/negation tactic proposals | Lean checks binder scope and side conditions |
| Equality | Substitution, congruence closure and equality-normalization proposals | `subst_vars`, `grind`, `simp_all`, congruence |
| AC normalization | Associativity and commutativity proposals | `ac_rfl` and logical simp lemmas |
| Linear arithmetic | Integer/natural arithmetic and bound/contradiction proposals | `omega`; optional Mathlib `linarith` |
| Polynomial arithmetic | Polynomial, nonlinear and numeric proposals | Mathlib `ring`, `ring_nf`, `nlinarith`, `norm_num`, `positivity` |
| Rational normalization | Denominator/cast normalization proposals | Mathlib; all denominator side conditions remain obligations |
| Bit-vectors | Bit-vector decision/simplification proposals | `bv_decide` requires `Std.Tactic.BVDecide` |
| Sets/functions | Extensionality, pointwise and membership proposals | Set tactics require Mathlib; core function extensionality is available |
| Datatypes | Injectivity, disjointness and constructor simplification proposals | Existing constructors and project imports |
| Proof structure | Unused single-line local deletion, witness/constructor packing, existing binder/branch folds | Lexical hints only; each resulting body is compiled |
| Simp sets/branches | One-at-a-time/bulk lemma deletion, repeated-normalizer folds, bounded branch closers | No global simp attributes or theorem statements are changed |

The native Boolean algorithms live in `jevops.logic_ir`; the declarative
catalog and Lean proposal generators live in `jevops.logic_refactor`. Optional
Mathlib tactics are proposals, not bundled reimplementations of those solvers.
They may be unavailable or inapplicable in a given project; compilation rejects
those candidates. The search does not silently add imports.

## API examples

```python
from jevops.logic_ir import (
    parse_formula, minimize_formula, karnaugh_map, detect_invariants,
    check_inductive_invariant,
)
from jevops.logic_refactor import equivalence_proof, reduction_sweep

f = parse_formula("(p ∧ q) ∨ (p ∧ ¬ q)")
assert minimize_formula(f)["lean"] == "p"
cells = karnaugh_map(f)
facts = detect_invariants(parse_formula("p ∧ (p → q) ∧ q"))

receipt = check_inductive_invariant(
    parse_formula("x ↔ y"),
    parse_formula("¬ x ∧ ¬ y"),
    parse_formula("(xn ↔ ¬ x) ∧ (yn ↔ ¬ y)"),
    {"x": "xn", "y": "yn"},
)
assert receipt["inductive"]

# This returns tactic text for a Lean obligation, not a trusted certificate.
proof = equivalence_proof("(p ∧ q) ∨ (p ∧ ¬ q)", "p")
# Compile as: example (p q : Prop) : ((p ∧ q) ∨ (p ∧ ¬ q)) ↔ p := by ...
drafts = reduction_sweep(
    "classical\nby_cases p <;> by_cases q <;> simp_all",
    goal="((p ∧ q) ∨ (p ∧ ¬ q)) ↔ p",
    requested=["boolean_minimize"], cap=12,
)
```

Conditional minimization takes an explicit `assumptions=Formula` argument.
For example, `p ∨ q` minimizes to `True` under `p`, but not unconditionally.
Receipts include the assumptions, don't-care count and vacuity flag. Certificates
with assumptions prove `assumptions → (original ↔ reduced)`. The automatic router
currently minimizes goals **without** introducing implicit context assumptions.
Router invariant summaries explicitly label consequences of assuming the goal
as `goal_consequences_not_hypotheses`; they are not facts available for proving it.

Unsupported syntax (predicate applications, equality, quantifiers, arithmetic,
Lean macros) is not guessed into Boolean semantics. `analyze_formula` reports
`supported=False`; the compiler-gated tactic families can still explore it.
Identifiers must actually elaborate as propositions for generated case proofs
to succeed in Lean.

## Search, training and safety

`RouterTuningConfig(logic_reductions=True, max_logic_candidates=12)` enables
the branch by default. The CLI exposes `--no-logic-reductions` and
`--max-logic-candidates`. These are candidate ceilings, not guaranteed quotas:
the overall compiler pool is shared with router, replay, composition and hammer
branches. Explicit router strategies receive router-branch capacity. Reduction
families are interleaved, with their starting position rotating each round.

Requested router families now receive a first probe before one family's
remaining variants fill the router quota. Branch closers prioritize large
case arms and can retain short leading simplification/introduction sequences;
simp-set pruning can remove the same lemma at multiple repeated sites. These
are hypotheses, not unconditional rewrites. Compiler failures are carried as
bounded diagnostics into the next router prompt, whose JSON stays complete
under the character budget. Identical rejected bodies do not consume more
candidate slots later in the same immutable compiler context; a new run can
retry them. Receipts expose `known_failure_skips`.

The historical 392-token proof has 81 lines. Local edits previously hit the
80-line model-response cap before reaching Lean. They now share the existing
bounded historical/composition allowance (at most 160 lines), while direct
LLM tactic text keeps its stricter cap. Character and unsafe-text checks still
apply. Multi-line case replacements now rebase every line, preserving nested
layout; previously only the first line was indented.

Every draft is rendered inside the original theorem envelope and passed through
the same compiler admission path. Python semantic equivalence, IR similarity,
TypeSafe/NCA signals, and short text are not proof authority. Structural deletions
are particularly dependent on Lean checking their contextual validity.

Receipts retain rule family/provenance, compilation outcomes, candidate counts,
token counts, and NCA feedback. Failed candidates receive failure observations,
not supervised proof targets. Only compiler-admitted strict shortenings can be
teacher examples. Existing cross-entropy/cosine diagnostics measure the model's
own prediction separately from the winning search target; representation-regression
rollback remains in place. This branch does not change holdout assignments or
authorize training on held-out data. Callers must keep evaluation canaries out
of training runs (`train=False` alone still permits search/NCA memory updates;
use separate evaluation memory).

The encoder now preserves goal parentheses and splits the declaration's colon
outside binders, rather than splitting inside a typed quantifier. Router IR
edits also invalidate/project stale scripts so the changed operations are
actually rendered. These remain bounded lexical IR helpers, not a complete
Lean parser or elaborator.

## Resource limits and validation

- Inputs: 8 Boolean variables, 256 AST nodes, depth 48, 8,192 characters.
- Exact cover: 20,000 search visits by default, hard cap 100,000. Exhaustion
  returns an independently truth-checked greedy cover with `optimal_two_level=False`.
- NNF: 2,048 recursive expansion visits by default, hard cap 4,096. Exhaustion
  is reported separately so other analyses remain available.
- K-map display and Lean truth-case proof generation: at most 6 variables.
- DNF/CNF output may exceed the input AST budget (e.g. parity). Large outputs
  are not automatically reparsed/accepted as new inputs; compact router summaries
  omit oversized formulas rather than truncating syntax.
- Bounded proposals, cached detached analyses, compile deduplication and existing
  compiler timeouts control work. This is not a demonstrated trillion-token pipeline.

`tests/test_logic_ir.py` checks all 256 three-variable functions in both normal
forms, compares minimum costs to an independent cube/coverage solver, and checks
random formulas, BDD evaluation, contextual equivalence, vacuity, counterexamples
and limits. `tests/test_logic_refactor.py` compiles generated certificates and
core-family fixtures with Lean, rejects a false equivalence, and exercises
compiler-gated teacher/NCA feedback and IR regression cases.

## Pinned-environment validation

Optional Mathlib tests use an existing, built Lake project; they never download
dependencies during a test:

```bash
JEVOPS_MATHLIB_PROJECT=/path/to/built/project python -m pytest -q tests/test_logic_mathlib.py
```

The fixtures compile emitted `ring`, `nlinarith`, `norm_num`, `positivity`,
`linarith`, `field_simp`, set-extensionality, quantifier-negation and `tauto`
proposals. They also reject `x / x = 1` without a nonzero condition. These nine
positive cases and the negative case passed in the arena's cached physlib
Mathlib environment on Lean 4.32.0. This establishes tactic availability and
fixture correctness, not performance on every arena theorem.

A reproducible frozen-record probe runs with disposable per-record memory,
training disabled, network denied, and a deterministic strategy plan (no live
LLM call):

```bash
python papers/completion/lean_refactor_arena/harness/validate_logic_reductions.py \
  --name CallElimCorrect.substOldPostSubset --rounds 3 --pool 16 \
  --timeout 60 --output /tmp/logic-validation-new.json
```

The output must be a new file. By default historical proofs are recompiled as
seed proposals, so this is a **seeded regression**, not an unseen-canary result.
Use `--no-history` for an unseeded run; prior development on the same theorem
still prevents claiming it as unseen. The receipt records the reverified
historical count, search results, actual untrained model CE/cosine and verifier
results, compile diagnostics, and the frozen dataset digest. Counts use the
local proof-body tokenizer, not an unpublished official arena metric. Official
scores remain null.

The 2026-09-22 seeded probe of `CallElimCorrect.substOldPostSubset` on the
pinned Strata Lean 4.26.0 checkout produced:

| Measurement | Result |
| --- | --- |
| Original proof body | 482 local tokens |
| Historical best, recompiled | 392 local tokens |
| Best after three rounds | 392 local tokens (tie, not a new record) |
| Round candidate entries | 16 each; 9 / 9 / 10 verified (includes cached successes) |
| Compiler calls | 34 across the isolated run, including model diagnostics |
| Previously rejected proposals skipped | 0 / 9 / 17 per round (proposal occurrences, not unique bodies) |
| Untrained model's own reconstruction | 482 tokens, compiler accepted |
| Model CE / cosine against best target | 3.8918202981 / 0.489 |
| Model training step | 0; evaluation memory discarded |

The frozen dataset digest was
`6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804`.
Sub-392-token attempts were rejected by Lean. The model's valid reconstruction
is not a model-generated 392-token refactor, and this seeded development probe
is not evidence of holdout generalization. The rerun used a deterministic
strategy plan rather than a live LLM.

The final rerun includes the line-budget, scheduling, negative-cache and
multi-line layout fixes. The 320-token branch-prefix proposal now reaches
`grind` correctly but still fails to prove the goal. Removing shared
`getVars` simplification lemmas also fails: induction hypotheses no longer
match the remaining goal expressions. Neither rejection earns a shortening
reward. The frozen data remained unchanged and the cached Strata checkout
was clean after source restoration.

The validation work also hardened the shared compiler gate:

- A missing/nonzero exit code, timeout or process error fails admission even
  when no JSON diagnostics were parsed. Diagnostic overlays cannot override it.
- Every selected tag must return a successful receipt; inspecting only the
  first version is insufficient. Requested and selected pins are reported
  separately: locally installed-tag success is not all-requested-tag success.
- Repository splices restore source bytes on exceptions as well as success.
  The bridge refuses dirty cached source instead of overwriting it from Git.
- Putnam records use generated Lake projects rather than a nonexistent Git
  clone; missing cached projects fail closed under `network=deny`.
- `<;>` is parsed as a whole combinator, avoiding stray `<`/`>` in flat IR.
  Model diagnostics compile the predicted body inside the same frozen theorem
  envelope used for search candidates; synthetic decoder theorem names must
  not create spurious statement-prefix failures.

The native/model limitations above still apply. Passing these tests does not
establish a new high score or a trained autoencoder that generalizes.

## Isolated learned-deletion diagnostic

```bash
python -m jevops.training_probe --output /tmp/jevops-training-probe-new.json
```

This separately tests whether weight updates produce shorter **rendered model
predictions**, rather than substituting the search winner or target proof. It
verifies both endpoints of four synthetic training pairs before updating a
fresh model, then runs a fixed 40 epochs / 160 example updates. Two held-out
development fixtures, one negative control and eight randomized dependency
fixtures never enter the training batch. All source/target fixtures are now
compiler-checked before training so an invalid fixture is not blamed on the
model.
The output includes before/after predictions, compiler receipts, CE/cosine,
configuration and checkpoint; evaluation is asserted not to mutate the model.
No arena data or production memory is read or written. These hand-authored,
closely related fixtures are not random canaries or a generalization benchmark.

The check uncovered two training defects that are now covered by regressions:

- Replacing learned operations could retain a stale renderer script, executing
  the original proof while metrics described a deletion. Learned edits now
  project/invalidate that script through the same IR edit path as router edits.
- The label-smoothed logit gradient disagreed with the reported CE objective
  and omitted the softmax-temperature chain factor. Finite-difference tests
  now check it at temperatures 0.5, 1 and 2.

The raw-model ablation with learning rate 0.2, seed 17 and the fixed schedule gave:

| Held-out fixture | Model body tokens before → after | CE before → after | Cosine before → after | Lean after |
| --- | --- | --- | --- | --- |
| Proposition, unused local | 7 → 2 | 3.8918 → 0.2524 | 0.3535 → 0.7520 | Accepted |
| Natural equality, unused local | 7 → 2 | 3.8918 → 0.2383 | 0.3535 → 0.7700 | Accepted |
| Necessary local binding (negative control) | 6 → 2 | 3.8918 → 2.8022 | 0.5000 → 0.7995 | **Rejected** |

These counts use the core diagnostic tokenizer, **not** the arena probe's
tokenizer. The negative control is a real model failure, not a shortening win:
improved CE and cosine do not establish proof validity. The model's current
decoder filters operations already present in the source; this experiment
demonstrates deletion learning, not novel tactic synthesis or learned semantic
dependency analysis. Its checkpoint is experimental and is not promoted into
production memory. NCA-assisted theorem generalization is not established by
this experiment.

The integrated router trainer now rolls back an update if the primary model
prediction was compiler-valid before the update but invalid afterward, even
when CE and cosine improve. Rejection receipts preserve the attempted loss and
compiler failure separately from the restored checkpoint's diagnostics. This
is a per-example regression guard, not a substitute for disjoint canary and
holdout evaluation.

## Dependency-guarded decoding

`LeanIRAutoencoder.predict_ir` now defaults to a conservative lexical guard
implemented in `jevops.ir_dependencies`. In supported flat proofs, learned
deletions are limited to simple local `have` declarations. A reverse dependency
pass retains referenced declarations transitively, including references in
types and anonymous `this` bindings. Stateful commands/closers remain roots;
implicit-context readers such as `assumption`, `simp_all` and tactics containing
holes retain prior facts. Unsupported nested/control syntax, comments, escaped
identifiers, shadowed declarations, truncated/misaligned IR or analysis-budget
exhaustion suppresses the edit. The analysis is bounded to 256 operations and
32,768 source characters; this is not a full Lean dependency elaborator.

The guard never reads teacher targets. Its receipt distinguishes proposed,
kept and restored operation indices and explains restorations. A requested
`max_ops` limits the proposal, not the fallback: preserving dependencies may
exceed that limit. Neither guarded nor raw predictions bypass Lean admission.
`dependency_guard=False` exposes the raw model as an explicit ablation. Router
diagnostics carry guard receipts, and training-probe v2 compiles and measures
both outputs separately. Weights and CE are unchanged by the guard; cosine can
change because it also measures the actual predicted operation sequence.

With fixture seed `20260922`, the v2 probe accepted 11/11 non-training guarded
predictions versus 4/11 raw predictions. Four shortened: the two original
fixtures from 7 to 2 core tokens and two dead-binding chains from 11 to 2.
The other seven retained needed bindings. Repeating with fixture seed
`20260923` produced the same validity/shortening counts and identical model
weights (the training data and schedule were unchanged). All eight dependency fixtures use
fixed structural families with randomized names/literals, so these are
development controls, **not** unseen semantic families or arena canaries.
The checkpoint remains experimental; this is a guard improvement, not evidence
that the neural model learned dependencies.

The frozen checkpoint can also be evaluated separately from arena search:

```bash
python papers/completion/lean_refactor_arena/harness/validate_logic_reductions.py \
  --rounds 3 --pool 16 --timeout 60 \
  --model-checkpoint /tmp/jevops-training-probe-new.json \
  --output /tmp/jevops-checkpoint-arena-new.json
```

This validates the checkpoint digest, loads its configuration, reports guarded
and raw-model CE/cosine and compiler outcomes, and asserts weight immutability.
The checkpoint does not seed the search or enter production memory. Search
still uses a deterministic strategy plan and historical seeds; official scores
remain null. This is not a live-LLM run or a frozen holdout generalization test.

The frozen synthetic checkpoint (160 updates) was evaluated on
`CallElimCorrect.substOldPostSubset`, against the reverified 392-token search
target. It **does not transfer successfully** to the arena proof:

| Model path | Local arena body tokens | Lean | CE | Cosine |
| --- | --- | --- | --- | --- |
| Untrained reconstruction | 482 | Accepted | 3.8918 | 0.4890 |
| Toy-trained raw prediction | 50 | Rejected | 4.1941 | 0.2365 |
| Toy-trained guarded prediction | 482 | Accepted | 4.1941 | 0.7060 |

The guard refuses to flatten this unsupported structured proof and preserves
the source operations. That is a conservative fallback, not model compression.
CE is worse than the untrained baseline even though guarded cosine improves;
the checkpoint is not promoted. The separate three-round search still ties
392 tokens, with no new record and no official score.

This evaluation also exposed misleading length credit in diagnostic loss:
the invalid 50-token prediction had a positive minimality bonus despite its
zero admission reward. `loss_for_example` now requires an explicit successful
verifier signal for **any** minimality bonus, including caller-supplied ones.
Missing, failed, partial and nonfinite verification get zero length credit;
an explicit verifier failure also forces aggregate reward to zero despite
optimistic TypeSafe/fuzzy signals. Advisor fields remain separate soft signals.

Lean tactic behavior is documented in the official
[tactic reference](https://lean-lang.org/doc/reference/latest/Tactic-Proofs/Tactic-Reference/).
The project-pinned Lean compiler, not documentation version or Python analysis,
determines whether each candidate is admitted.

## Learned binding-retention head (2026-09-22)

The legacy decoder compares each observed operation's next-operation logit
against EOS. That does not directly supervise binding retention. An opt-in
binary logistic head now learns keep/delete decisions for supported flat
`have` declarations. Source-only symbolic features include reachability from
stateful proof steps, direct/indirect use, unused declarations and literal
`True.intro` facts. The weights are learned; dependency extraction is not.
This is neither a neural dependency-discovery system nor a general Lean AST
decoder, and it does not demonstrate trained NCA theorem generalization.

Supervision requires an exact, unambiguous source/target operation subsequence,
including operands, with the same goal/binders and no deleted stateful steps.
Reordered, replaced and ambiguously aligned operations are not deletion labels.
The router uses only compiler-admitted strict shortenings as teachers; the
standalone probe checks both endpoints before any update. Low-level model
training APIs still require callers to supply trusted training data.

Binding BCE has its own metric and coverage count, with default loss weight
0.25. Its stable softplus loss and gradient have finite-difference tests,
including saturated logits. Sequence CE and cosine remain separate metrics;
`ir_exact_match` now compares operands too. Checkpoints save binding weights
and update counts; old checkpoints retain legacy decoding. Training is opt-in
via `AutoencoderConfig(train_binding_policy=True)` or the corresponding router
flag; a loaded, trained head is used at inference even when training is off.

The existing post-decode guard remains independently switchable. Disabling
that guard evaluates the learned head; `binding_policy=False` additionally
selects the legacy decoder for a same-weights ablation. Unsupported structured
proofs explicitly abstain with `unsupported_identity`. The router offers raw
learned cuts separately because the lexical guard can retain unnecessary facts
before implicit-context tactics. An active head participates in branch budgeting
with one bounded raw-proposal slot before the local-candidate tail, so local
fanout cannot consume its allocated slot. Overall pool limits still apply.
Those proposals still pass through Lean;
failed proposals receive zero reward and zero minimality credit.

The canary gate rejects binding BCE regression, lost/changed measured coverage,
nonfinite observed metrics and lower verifier success. The router's primary
prediction rollback also checks binding BCE (0.02 tolerance) and loss of its
coverage, in addition to sequence CE, cosine and compiler regressions. These
checks do not replace a custodian-blind holdout or prove every decoded sample
valid. An empty canary remains explicitly unmeasured, not validation evidence.

Reproduce the isolated experiment:

```bash
python -m jevops.training_probe --curriculum balanced --train-binding-policy \
  --fixture-seed 20260922 --output /tmp/jevops-binding-probe-new.json
python papers/completion/lean_refactor_arena/harness/validate_logic_reductions.py \
  --rounds 3 --pool 16 --timeout 60 \
  --model-checkpoint /tmp/jevops-binding-probe-new.json \
  --output /tmp/jevops-binding-arena-new.json
```

The balanced curriculum contains four verified strict cuts that retain live
dependencies as well as deleting dead facts. With 40 epochs / 160 updates,
training binding BCE fell from 0.6931 to 0.2950. Evaluation includes the same
11 development controls used above, none of which entered the training batch:

| Decoder, same balanced checkpoint | Lean-valid predictions | Strict shortenings | Guard restorations |
| --- | --- | --- | --- |
| Legacy operation/EOS ablation | 11/11 | 0 | Disabled |
| Learned binding head, raw | 11/11 | 4 | Disabled |
| Learned binding head, guarded | 11/11 | 4 | 0 |

The four cuts are two 7→2 and two 11→2 core-token reductions. The two original
validation fixtures' mean sequence CE fell from 3.8918 to 0.9587, and their mean
cosine increased from 0.3535 to 0.8370. Repeating with fixture seed `20260924`
gave the same validity/shortening counts and identical checkpoint weights.
The old decoder also benefits from balanced training: it no longer deletes
needed facts on these controls, but it produces no shortening. These are fixed
structural families with randomized identifiers/literals, not unseen semantic
families, random arena canaries, or evidence of trillion-token throughput.

The separate arena evaluation on `CallElimCorrect.substOldPostSubset` remains
unsuccessful as learned compression:

| Path | Local arena body tokens | Lean | Sequence CE | Cosine |
| --- | --- | --- | --- | --- |
| Untrained reconstruction baseline | 482 | Accepted | 3.8918 | 0.4890 |
| Balanced checkpoint, legacy decoder | 50 | Rejected | 4.1838 | 0.2410 |
| Balanced checkpoint, raw binding head | 482 | Accepted | 4.1838 | 0.7105 |
| Balanced checkpoint, guarded head | 482 | Accepted | 4.1838 | 0.7105 |
| Separate three-round search | 392 | Accepted | Not model output | Not model output |

The head reports `unsupported_identity` / `source_ir_alignment` on this proof.
Binding BCE is unmeasured, not zero. Source preservation is not a learned
refactor. Sequence CE is worse than the baseline, so this checkpoint is not
promoted. Search still **ties**, rather than beats, the reverified historical
392-token result. It uses isolated memory and a deterministic router strategy
plan, not a live LLM; the evaluated checkpoint does not seed that search.
Official scores remain null.

Local receipts (temporary, not production artifacts):
`/tmp/jevops-binding-policy-RZZ0fM/balanced-head.json`,
`balanced-second-seed.json` and `arena-balanced-head.json` in that directory.
Checkpoint SHA-256:
`fc0252dff73f060678314cada16e90b862b77dd1fda0aa065154bf4f92a5522f`.
