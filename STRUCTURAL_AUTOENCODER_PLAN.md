# Structural autoencoder and JeV surrogate learning plan

Status: the bounded JeV score adapter and sparse expected-utility update are
implemented as opt-in APIs. A bounded [native expression DAG codec](EXPR_DAG_CODEC.md)
is also implemented for closed expressions and scalar metadata. Its
[training-pair bridge](STRUCTURAL_TRAINING.md) now gates endpoint supervision in
the isolated distillation runner and retains the native graphs. A separate
[source-DAG feature experiment](STRUCTURAL_FEATURES.md) trains a sparse readout
over fixed neighborhoods with matched lexical/structural ablations. A bounded
[proof-state observation exporter](PROOF_STATE_CAPTURE.md) now retains native
before/after contexts and conservatively groups coupled goals. The new
[closing-replay bridge](PROOF_REPLAY.md) regenerates contexts from source and
feeds independently whole-proof-checked shorter results to an isolated sparse
edit-head training experiment with CE/cosine and frozen reconstruction. Its bounded
cross-structure curriculum now retains failed reference/cost checks and distinguishes
no-applicable-rule preservation from learned selection; the local-let challenge
exposes a unique-DAG-size regression despite shorter syntax. A separate atomic
closing-span curriculum now teaches two-line alias elimination with the same
strict endpoint gates. Newly mined let-deletion rules retain continuation context;
the inspected failure is a post-freeze regression probe, excluded from training
and new protocol gates. The original failing benchmark is unchanged. An opt-in
router-refinement bridge now feeds training-only rejection/cost diagnostics back
to bounded proposal rounds before teacher/grammar freeze. Native tests use an
explicit offline fixture, not a hosted model. A separate optional
[trainable DAG edit policy](TRAINABLE_GRAPH_POLICY.md) now backpropagates CE/cosine
through binder-aware ordered message passing, with a request-bound JeV objective,
frozen-encoder/node-only controls and an isolated native-checking runner. A
training-only multiscale/batch/LR refinement now freezes selection before
new-layout transfer checks; validity improves, but per-split savings and CE/cosine
still reject promotion against fixed features. The original failed v1 baseline
remains reproducible. Its
decoder still uses the lexical copy grammar: typed-by-construction decoding,
lossless neural reconstruction, replayable open-state serialization, learned
critic/NCA gradients and production outer-runner promotion remain planned.
Updated 2026-09-22. The previous
baseline is recorded in [proof-cost-aware compression](KERNEL_COMPRESSION_NEXT.md).

## Lossy proposals can still teach the model

Keep the sparse autoencoder as a useful baseline and proposal policy. Exact
reconstruction is not a prerequisite for a learning signal: JeV can act as a
fuzzy function approximator, assessing partial semantic preservation, likely
repairability, and relative candidate quality. Failed or lossy outputs need not
be discarded from feedback collection. This does not make them verified proofs
or turn the latent representation into a lossless codec.

An available JeV scorer supplies feedback, not automatically a derivative with
respect to autoencoder parameters. The adapter must connect that feedback to
the policy's probabilities. This distinction is especially important for the
current discrete Choice/Score/Noul interface: rubric indices are not calibrated
probabilities, and a black-box scoring call is not an autograd operation.

Current code boundaries:

- `autoencoder.jev_rank_variations` invokes an injected JeV advisor and orders
  candidates; it does not compute a JeV policy gradient.
- `autoencoder_training.train_example` uses a supplied reward to scale
  supervised updates by `0.5 + 0.5 * clip(reward)`. This is reward-weighted
  supervised learning, not optimization of expected JeV reward.
- `loss_for_example` reports fuzzy reward terms; adding those scalar terms to
  a diagnostic total does not differentiate them through discrete predictions.
- `rewrite_policy.probabilities` already exposes a differentiable distribution
  over a bounded edit set. `jev_surrogate.expected_utility_gradient` now computes
  its JeV utility gradient, with an optional frozen-reference KL penalty.
- `LeanIRAutoencoder.jev_feedback_request` and `train_jev_feedback` expose a
  separate, training-only update path. Its default weight is zero. Existing
  training loops are unchanged; no hosted scorer is automatically called.

## Two feedback paths, one proof authority

```text
source + context -> sparse/structural policy -> candidate edits
    ^                                           |          |
    |                       JeV/NCA assessments <-+          |
    +-- expected-reward gradient / critic learning          |
    |                                                      v
    +-- verified teacher pairs <- cost/axiom gates <- Lean checking
```

Keep a separate failure/repair buffer alongside the verified teacher buffer.
It may contain invalid and unevaluated candidates, diagnostics, JeV scores and
repair trajectories, but never label them successful compression targets.
Only exact rendered candidates checked in their original theorem environment
can enter the verified-refactor teacher buffer. Strict expression-cost policy
must be explicitly enabled; the current router does not inherit it implicitly.

## Implemented increment: expected JeV reward on the sparse edit policy

For a fixed training source and frozen candidate set, let `z_i` be the raw
policy logit, `p_i = softmax(z / T)_i`, and `r_i` a bounded JeV-derived score
held constant during the update. Optimize:

```text
L_JeV = -sum_i p_i * r_i
dL_JeV/dz_j = p_j * (sum_i p_i * r_i - r_j) / T
```

This is an exact gradient of the finite-set surrogate objective, not a
derivative through JeV and not a gradient of theorem truth. Backpropagate the
logit derivatives through the existing sparse features. Score identity as well
as edits. Freeze the scorer/rubric and candidate set within an update; changing
either requires a fresh receipt. Identical rewards must produce zero gradient.
Deduplicate candidates and bind scores by source/context and candidate digests,
not positional IDs reused across examples.

For larger sampled edit sequences, use a score-function/policy-gradient
estimator with a detached, action-independent baseline and recorded sampling
probabilities. Do not treat deterministic argmax drafts or old search winners
as on-policy samples. This route does not require differentiating the discrete
output or the scorer; stochastic computation graph methods supply the relevant
gradient-estimation framework. [Schulman et al.](https://arxiv.org/abs/1506.05254)

Choice-only feedback should use an explicit preference objective; Score feedback
needs a versioned ordinal-to-utility mapping, not an assumed probability of
correctness. Preserve Noul/abstention separately. Missing, malformed or nonfinite
feedback skips the auxiliary update and records coverage; it is not a zero or
perfect label. The default mode remains off and offline fixtures remain usable.

The implementation binds receipts to source, caller-supplied environment digest,
grammar, policy weights/step/temperature, scorer ID and rubric mapping. The caller
must supply honest training-split membership and an actual pinned environment
fingerprint; a string label or receipt hash does not authenticate either. Requests
include full candidate text and abstain rather than truncate beyond a fixed text
budget. Tests use explicitly offline scorer fixtures, not a hosted JeV model.

Use the following API after preparing the training-only edit grammar. `source`
must be a training example; `environment_digest` and `scorer` are supplied by the
consumer. Scores are candidate-ID-keyed rubric labels, not verification results.

```python
from jevops.jev_surrogate import JeVFeedbackSpec, collect_feedback

spec = JeVFeedbackSpec(
    context_sha256=environment_digest,
    scorer_id="configured-scorer-and-version",
    rubric_id="repair-utility/v1",
    utilities={"0": -1.0, "2": 0.0, "4": 1.0},
)
reference = dict(model.state["rewrite_weights"])  # Freeze once across rounds.
for _ in range(3):
    request = model.jev_feedback_request(source, spec=spec, split="train")
    # scorer(request) returns {"scores": {candidate_id: label, ...}};
    # it may instead explicitly abstain. All candidates, including identity,
    # need scores for an auxiliary update to proceed.
    receipt = collect_feedback(request, scorer)
    update = model.train_jev_feedback(
        source, receipt, spec=spec, split="train", weight=0.1,
        reference_weights=reference, kl_weight=0.1,
    )
```

The update checks all inputs before changing edit weights, applies gradient
clipping, and leaves reconstruction parameters and the template bank untouched.
No supervisor labels, verified-success rewards or admission records are created.
Run ordinary supervised updates separately; their change to the policy invalidates
an old JeV receipt. A zero gradient/disabled update leaves the entire state intact.
Returned before/after utility and KL values are surrogate measurements, not Lean
or arena results. CE/cosine must still be evaluated on their own fixed targets.

## Objectives and protection against reward hacking

Keep reconstruction CE, verified-edit CE, expected cosine loss, JeV surrogate
loss, and optional reference-policy KL separately weighted and reported.
JeV supplements rather than replaces CE/cosine. Before optimizing a component,
document its derivative path; logged metrics are not necessarily trained losses.
Frozen reconstruction heads remain an explicit option, reported as frozen rather
than improved. Tune weights and learning rate on development data only.

Separate approximate progress from verified success. JeV can grade a failed
candidate's repair potential, but an invalid or unchecked candidate earns no
verified compression reward and cannot pass admission. Bind positive size reward
to actual cost receipts, with helper definitions included. Check the unchanged
theorem statement/context, forbidden admissions and transitive axiom policy.
The fuzzy advisor cannot weaken those checks or supply replacement measurements.

Bound auxiliary rewards and gradient norms, regularize toward a frozen baseline,
and audit score-versus-Lean disagreements. Reward-model confidence must be
calibrated on separate development data before being presented as confidence in
validity. Keep syntax failures, Lean failures, timeout/unknown, valid-but-larger,
and valid-smaller outcomes distinct; a timeout is not proof of invalidity.

## Structural architecture and cellular-automaton integration

1. **Lossless representation lane (bounded codec implemented).** The
   [expression DAG codec](EXPR_DAG_CODEC.md) preserves native closed expressions,
   binder information, universe levels and scalar metadata, with exact round
   trips and kernel rechecking of exported theorems. Syntax metadata/open contexts
   are rejected; full dependency-closure authentication remains separate. Exact
   source reconstruction still needs syntax/trivia storage. This lane is
   independent of whether the learned proposal model is lossy.
2. **Structural learning lane.** Attach relevant `InfoTree` provenance and proof
   states to the expression representation. Compare structural retrieval and the
   current sparse policy with a graph/tree encoder plus typed edit decoder.
   `InfoTree` is elaboration metadata, not the core proof DAG.
   The implemented endpoint bridge retains checked source/target DAGs and feeds
   accepted text targets to the existing sparse learner; it does not yet train
   on graph features or capture open proof states.
   The separate single-step structural head now uses source-only graph features;
   its fixed encoder, independent checkpoint and extra source-export cost are
   explicit. The separate proof-state exporter now captures local declarations,
   reachable metavariable assignments and universe dependencies for analysis.
   Its training-only collector creates observations, not executable transitions
   or verified teacher labels. Delayed assignments are explicitly unsupported;
   full state replay and policy/critic training on these observations remain future
   work. Default autoencoder/outer-runner behavior remains unchanged.
   [Lean elaboration reference](https://lean-lang.org/doc/reference/latest/Elaboration-and-Compilation/)
3. **Amortized JeV critic.** Cache JeV observations and optionally distill them
   into a local differentiable critic, with separately supervised heads for
   measured Lean outcomes/costs. Validate disagreement and calibration before
   using it to save scoring calls. Freeze critic parameters for policy updates;
   use alternating refreshes. Gradients through continuous relaxations are biased
   surrogates unless justified; they are not gradients through emitted Lean.
   Preference-based reward learning is a precedent, not evidence that this
   implementation already works. [Christiano et al.](https://arxiv.org/abs/1706.03741)
4. **NCA guidance.** Record cells/rules, intermediate states, feedback provenance
   and compiler outcomes. Initially use bounded scores or scheduling features.
   Any differentiable NCA critic is a separate, tested implementation; the current
   typed Horn automaton does not imply end-to-end differentiability. Do not count
   JeV-derived NCA scores as independent confirming evidence.
5. **Outer/inner loop.** Let the outer router propose tactics, repairs and
   hypotheses from training/development evidence. Let the inner loop enumerate,
   score, check and collect receipts. Distill checked improvements; use failures
   for critic/repair learning. Preserve separate measurements for raw model
   predictions, search-assisted outputs and repaired outputs.

## Implementation order and acceptance tests

| Increment | Completion evidence required |
| --- | --- |
| Versioned JeV feedback adapter (implemented) | Stable candidate/context IDs; explicit rubric/abstention semantics; deterministic fixtures; no hosted-provider calls in unit tests |
| Sparse expected-reward update (implemented) | Finite-difference agreement at multiple temperatures, with/without KL; higher reward increases relative probability; constant rewards give zero; disabling JeV preserves the baseline |
| Isolated training API (implemented); outer wiring (planned) | Malformed or cross-source receipts cannot update weights; real Lean rejects a high-scoring invalid draft; this API never creates teachers or admits proofs |
| Bounded typed DAG codec (implemented); richer structural views (planned) | Native binder/universe/scalar-metadata round trips, corruption rejection, kernel recheck; open contexts and full dependency-closure verification remain out of scope |
| Structural training pairs (implemented, opt-in) | Fresh train-only endpoint checks, exact declared types, no axiom/node growth, target-IR fidelity, explicit rejection coverage; graphs retained while sparse CE/cosine still drive learning |
| Fixed source-DAG feature readout (implemented, isolated) | Single-step matched lexical/structural arms, actual CE/cosine gradients, context/checkpoint binding, raw native checks and weight ablations; no trained graph encoder or additional arena savings demonstrated |
| Trainable source-DAG edit policy (implemented, isolated/optional) | Real embedding/message-passing gradients and finite differences, CE/cosine plus request-bound JeV/KL, frozen-encoder and node-only controls, native raw-output checking; decoder remains lexical and no arena promotion |
| Training-only graph refinement (implemented, isolated) | Versioned multiscale readout, atomic mean-gradient batches, bounded training-only LR grid, freeze-before-generation transfer protocol, name-insensitive shape overlap checks and per-split CE/cosine/cost gates; improved validity but no baseline compression advantage or promotion |
| Context-aware observations and coupling analysis (implemented, isolated) | Native before/after captures, term/universe/context dependency closure, explicit unsupported cases, bounded training-only collection and generated reports; no replay, teacher admission or model update |
| Native closing replay and atomic endpoint distillation (implemented, isolated) | Original-environment checks, bounded train-only teacher search, selected span/pair provenance, raw one-edit CE/cosine evaluation and frozen reconstruction; known regressions separate from final protocol holdouts; no arena promotion |
| Router feedback refinement (implemented, opt-in/isolated) | Training-only checked feedback between bounded batches, strict request-bound proposals, cost diagnostics, route/fixture provenance and no evaluation-time router access; no hosted-model performance claim or production promotion |
| Structural critic / NCA experiments | Matched sparse/WL/graph ablations, measured calibration, critic-frozen policy updates, independent evaluation of the proposed gradient path |
| Arena comparison and promotion | Same task set, imports, tokenizer, budget and historical seed; raw and search-assisted results separate; CE/cosine/validity/cost coverage and nonregression gates |

Split by theorem/repository/structural family, not only random renaming. Final
canaries must not supply templates, JeV preferences, critic targets, router
prompts, reward-weight choices or learning-rate tuning. Use development cases for
repeated adaptation; repeatedly inspected holdouts are no longer untouched final
tests. Freeze model/scorer versions before final evaluation and hash all receipts.

Use `refactor_report` for measured reports, with separate surrogate-training and
verified-evaluation sections when that schema extension is implemented. Report
stored bytes, source tokens, expression nodes, validity, compile time, scoring
calls and wall time independently. Neither a rising JeV score nor a lower CE
alone demonstrates a new arena high score or lossless compression.

Reproduce the focused checks with `python -m pytest -q tests/test_jev_surrogate.py`.
They include multiple fixture-scored training rounds, operation-CE preservation,
edit CE/cosine improvement on an aligned fixture, and real Lean good/bad cases
when Lean is installed. The renamed good case is not an unseen-family benchmark.
