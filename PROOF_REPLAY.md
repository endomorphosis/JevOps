# Native closing replay and checked teacher distillation

`jevops.proof_replay` regenerates native contexts from original Lean source and
replays both an observed closing event and its proposed replacement independently.
`jevops.replay_distillation` trains the existing sparse edit head on shorter outputs
that also pass the whole-proof structural gate. Both are opt-in; the production
outer router is unchanged.

For scope/type-guided local-reference and dependent-application proposals, see
[scoped teacher discovery and graph training](SCOPED_TRAINING.md). This optional
proposal source uses the same native replay and whole-source admission boundary.

The [local library-premise provider](ARENA_PROVIDERS.md#local-premise-replay-opt-in)
also supplies collector-compatible `event_id`/`candidate` proposals. Its bounded
query uses constant names in captured before-goal/local types; root-qualified
library references remain untrusted until regenerated-context replay and fresh
whole-source checking. It does not replace the structural local-term proposer.

## Verification boundaries

[Observation JSON](PROOF_STATE_CAPTURE.md) is still a projection, not a decoded
checkpoint. Re-elaboration must reproduce the exact saved event, before/after
states, namespace, toolchain and source span. Stale anchors abstain. Lean normalizes
CRLF; exported spans are mapped back to the original UTF-8 source bytes.

Before either tactic runs, each original visible goal is abstracted into a closed
local telescope. Closing results must assign every original goal a closed proof
that Lean's kernel checks against that original type in the **original environment**.
Transitive axioms are audited against that original environment even if a tactic
replaces its elaborator environment. The Arena adapter injects its existing
whole-proof audit for module contexts: matching private imported proof bodies
are loaded for transitive inspection only, never exposed to tactic elaboration.
This distinguishes public axiom-shaped views of imported theorems from actual
axioms. The allowed set remains `propext`, `Classical.choice`, and `Quot.sound`.
The standalone default audits the original environment without this adapter.
`sorry`, wrong-type assignments, and simply
emptying the tactic goal list are rejected.

Telescope abstraction explicitly generalizes opaque `nondep` have-bindings,
following Lean's native semantics; it does not unfold their potentially stale
hidden values. Transparent lets remain definitions. This matches the V2
observation contract without making those observations executable checkpoints.

This uses Lean's native
[InfoTree APIs](https://lean-lang.org/doc/api/Lean/Elab/InfoTree/Types.html) and
addresses dependency/false-positive concerns in
[LeanTree §§3.3–3.4](https://arxiv.org/html/2507.14722v1), without porting LeanTree.
Only 1–16 goals with closed telescopes are supported. Unresolved shared term or
universe witnesses abstain. Remaining goals produce `open_goals`, not successful
transition replay. Success reproduces a closing outcome, not an identical proof
term, and a focused/nested event need not cover the whole theorem.

Local success leaves `proof_admitted=False` and `whole_source_checked=False`.
Synthetic `null` branch-header nodes and bare `=>` source spans can carry valid
InfoTree observations, but are not editable closing tactics. The shared source
replacement helper rejects them; diagnostics retain the original events.
The collector replaces only the captured span, then independently applies the
[structural teacher gate](STRUCTURAL_TRAINING.md): unchanged single-theorem envelope,
exact elaborated type/universes, fresh original/candidate compilation, standard
axioms with no dependency growth, fewer proof-source tokens, non-growing unique
and expanded proof-expression nodes, and supported exact tactic IR.

The standalone collector still abstains on complex preludes, custom definitions
and namespace wrappers. The explicit
[Arena project adapter](ARENA_PROVIDERS.md#arena-project-context-and-controlled-comparison)
instead captures/replays the target in the native verifier's target-free prefix,
preserving its open namespaces/sections and target-relative source offsets.
Its project-bound captures cannot use the ambient standalone replay path.
Local replay success still requires independent all-pin whole-proof admission;
this adapter does not bypass the collector's separate structural teacher gate.
Baseline tactics are proposals, not universally valid rules. `proposal_fn` accepts
bounded caller-supplied/LLM proposals; no hosted model is called automatically.
Executable source/imports/tactic metaprograms and callbacks are trusted. Time,
output and traversal bounds are not an OS sandbox or a compiler-memory guarantee.
Hashes bind artifacts but do not authenticate complete dependency closure.

## Training and reports

```bash
python -m jevops.replay_distillation --project-root /path/to/project --lake \
  --environment-sha256 "$DEPENDENCY_MANIFEST_SHA256" --epochs 24 \
  --output-dir /path/to/new-replay-run
python -m pytest -q tests/test_proof_replay.py tests/test_replay_distillation.py
```

Omit `--lake` for Lean-core controls. The CLI refuses an existing destination and
generates `run.json` (attempts, checkpoints, compiler receipts) and a compact
`summary.md` in code. Success means experiment gates passed, not an arena score.

The control has one renamed example per train/validation/canary/holdout split.
Search tries `rfl` (invalid here) and `assumption` for `exact id h`. Only independently
admitted targets become teachers. Training never reads prewritten labels or
evaluation sources; grammar mining precedes fixed-grammar metric baselines.

The default 24 epochs train edit cross-entropy plus expected cosine loss,
using existing scheduling and gradient clipping. Operation/latent reconstruction
parameters are frozen and checked for exact equality; operation CE is reported.
Cosine measures IR/features, not theorem equivalence. Predictions are committed
before target access and independently checked without repair or teacher fallback.
Final holdout access follows checkpoint freeze; a zero-edit-weight ablation uses
the same grammar. No updates follow holdout evaluation. Minimality reward and
verified savings require strict shortening and expression-cost nonregression.

This is a same-family plumbing/learning control, not mathematical generalization,
global minimality, arena performance or throughput evidence. It trains sparse
source-feature edit weights, not a graph autoencoder, open-state encoder, JeV or
NCA. No checkpoint is promoted. The separate [JeV surrogate path](STRUCTURAL_AUTOENCODER_PLAN.md)
remains available for lossy-candidate feedback without relaxing teacher admission.

## Cross-structure transfer controls

`--curriculum transfer --seed 20260922` uses `replay_curriculum.transfer_rows`:
three training families (hypothesis reuse, reflexivity, truth introduction), three
renamed validation and canary examples each, and six final holdouts. The holdouts
exercise `intro`, a polymorphic list type, a local `let`, a conjunction branch,
and two preservation controls with no applicable template. These share rewrite
motifs, not disjoint mathematical concepts; there is no semantic-decontamination
claim. With three training pairs, 24 epochs mean **72** parameter updates.

```bash
python -m jevops.replay_distillation --project-root /path/to/core-project \
  --environment-sha256 "$DEPENDENCY_MANIFEST_SHA256" --curriculum transfer \
  --seed 20260922 --epochs 24 --max-compiles 96 --output-dir /path/to/new-transfer-run
python -m pytest -q tests/test_replay_curriculum.py
```

The bounded teacher hammer tries `rfl`, `assumption`, then `trivial`. Equal-token
admitted candidates retain proposal priority rather than a hash ordering that
changes when theorem names change. Only the three training sources reach capture,
replay and template mining. Exact/whitespace source duplicates are rejected;
holdout duplicate checks occur lazily after freezing rather than reading holdout
content during manifest validation. Split/family provenance remains caller-owned.

Evaluation retains failed reference gates with `loss=null`; it neither computes
supervised losses against rejected targets nor drops those rows from sample,
validity and token denominators. Reports include loss coverage, reachable labels,
family-level results, cost-safe counts, and cases with no applicable edit. Incomplete
target/label coverage or any proof-cost regression fails `coverage_and_cost` and
the overall experiment, even when every raw prediction compiles. Preservation
because a rule is inapplicable is not evidence of learned semantic discrimination.

The fixed Lean 4.34 control currently exposes a real counterexample to treating
shorter syntax as smaller proof DAGs: under `let y := x`, replacing `exact Eq.refl y`
with `rfl` reduces source tokens 10 → 6 but increases unique expression nodes 7 → 8;
expanded size remains 10. Keep this challenge and its failed gate. It receives no
verified compression reward and no positive teacher label. The transfer CLI is
therefore expected to save its full diagnostic report and exit nonzero on that
toolchain; this is not a failed test of the reporting machinery.

An inspected holdout is now known evidence. Reruns are reproducibility/regression
checks, not new blind trials. Future model/rule changes need a fresh evaluation
protocol; do not silently recycle these held-out failures into the current training
split, change the reference, or relax the gate to make the report pass.

## Atomic closing-span curriculum

`--curriculum compound` is a **separate protocol**, not a changed reference for
the transfer benchmark. It adds two training motifs: `let y := x; exact Eq.refl y`
to `rfl`, and `let y := x; rfl` to `rfl`. With five verified training pairs,
24 epochs perform 120 sparse edit-head updates. Validation and canary splits
each contain five renamed controls. Six final holdouts exercise introduced,
polymorphic-list and branch contexts plus two no-applicable-rule controls,
including an existential witness that requires its binding. These are designed
shared-motif tests, not blind mathematical-family holdouts.
The default whole-source compiler-call budget is 128 for this curriculum
(48 for the older modes); callers may set a smaller explicit budget.

```bash
python -m jevops.replay_distillation --project-root /path/to/core-project \
  --environment-sha256 "$DEPENDENCY_MANIFEST_SHA256" --curriculum compound \
  --epochs 24 --max-compiles 128 --output-dir /path/to/new-compound-run
python -m pytest -q tests/test_compound_replay.py tests/test_rewrite_policy.py
```

The same bounded hammer tries whole closing spans before nested closing events.
The two-line alias rewrite is one atomic edit, not a cost-growing intermediate
followed by a second accepted step. Both endpoints must pass the unchanged
whole-proof gate. `selected_proposals` binds each admitted teacher to the chosen
native event/span, replay digest and structural pair digest. Rejected partial
edits remain in `attempts`; raw model edit traces are saved with evaluation rows.
Inference still uses one edit, with no solver repair or label access.

Newly mined pure-`let` deletion templates retain their entire unchanged
continuation, rather than becoming context-free binding deletions. For example,
`let y := x; rfl → rfl` does not match `let y := x; exact ⟨y, rfl⟩`.
Mining abstains when this exceeds the eight-line bound or crosses an enclosing
indentation scope. This is conservative lexical context retention, **not** a
liveness/type proof. Existing saved template banks are not silently migrated;
regeneration needs new fixed-grammar CE/cosine baselines and fresh Lean checks.

Only after checkpoint freeze and final holdout evaluation does the runner load
the inspected transfer failure as a `known_regressions` probe. It records the
original failed reference and its fresh check alongside the new atomic target.
The probe has a separate manifest/digest, never supplies training templates or
weights, and never enters current holdout aggregates or gates. Its successful
repair would be a regression result, not fresh generalization. The original
`transfer_rows` benchmark and its failing expectation remain unchanged.

Neither this curriculum nor a passing gate promotes a checkpoint or trains a
graph encoder, JeV critic or NCA. Production outer-loop wiring and matched arena
evaluation remain separate work.

## Opt-in router refinement before teacher/grammar freeze

`jevops.replay_router.run_router_experiment` connects the existing `llm_router`
facade (or an injected generator) to this isolated experiment. It does **not**
enable the legacy `RouterTuner` online learner or change its promotion policy.
The initial bounded hammer is unchanged. On a training source where its result
is absent or longer than one proof-body token, up to three refinement rounds
receive captured closing spans, local replay outcomes, and whole-source gate
decisions. Cost failures now retain measured before/after expression sizes.
The router may repair a candidate or propose a new tactic/composition hypothesis.

Every batch is checked before the next feedback request. All batches together
have a maximum of 16 proposal attempts per source, including duplicates; duplicate
endpoints are not replayed again. The adapter emits at most four proposals per
call, defaults to 16 provider calls overall, and stops querying a source once a
one-token teacher is admitted. That is a lexical lower bound for this restricted
proof body, not a global minimality theorem. Empty/malformed/failed responses
abstain without hidden retries or provider fallback.

```bash
python -m jevops.replay_distillation --project-root /path/to/core-project \
  --environment-sha256 "$DEPENDENCY_MANIFEST_SHA256" --curriculum compound \
  --router-refinement-rounds 2 --max-router-calls 16 \
  --router-provider "$ROUTER_PROVIDER" --router-model "$ROUTER_MODEL" \
  --output-dir /path/to/new-router-replay-run
python -m pytest -q tests/test_replay_router.py
```

Router refinement is disabled by default. Enabling it requires an explicit
provider and model and may incur service costs. The adapter requires live route
attestation; missing/mismatched routes cannot create proposals. Execution policy
is inherited from the provider: a tool-enabled CLI generator is **not** made into
a sandboxed text-only service by this bridge. Callbacks, imports and Lean tactics
remain trusted execution infrastructure; the syntax filters are not an OS sandbox.
No live provider is invoked by the tests.

Responses must be strict, bounded JSON with the exact request hash, allowed event
IDs, tactic text and a bounded explanatory hypothesis. Duplicate JSON keys,
unknown fields (including claimed proof receipts), unlisted anchors, declarations,
metaprograms and oversized responses are rejected. Hypotheses never become proof
labels. Candidate text still needs native replay and the unchanged whole-source
type/axiom/cost/IR checks. Verified teachers that the bounded edit grammar cannot
represent produce an explicit failed experiment with zero updates, not fabricated
identity labels. This can mint learned span templates from checked outputs, not
arbitrary Python/Lean tactic definitions or global blacklist repairs.

Only training rows reach capture, the router and feedback. Grammar mining and
CE/cosine baselines follow teacher search; evaluation invokes neither the router
nor a repair search. Previously inspected regression probes remain post-freeze
and excluded from training and gates. The generated `run.json` includes router
requests, bounded responses, hypotheses, route provenance, attempt rounds and
selected teacher bindings; `summary.md` remains code-generated. Fixture callbacks
are labeled `offline_fixture`, arbitrary injected callbacks `injected_unattested`,
and an unknown live-use status stays unknown rather than being reported as a
successful hosted-model run. No checkpoint is promoted.

The native feedback test deliberately restricts one initial search to its
cost-growing partial rewrite, then scripts an open-goal proposal and an atomic
repair. It demonstrates rejection → feedback → checked teacher → sparse training,
not an LLM improvement over the unrestricted hammer, an arena high score, or
generalization to unseen mathematical families.
