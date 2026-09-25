# Learning verified Lean rewrites

Historical joint-training experiment. The newer
[certified-refactoring follow-up](CERTIFIED_REFACTORING.md) expands to 33 catalog
families, implements linear certificates, and evaluates an opt-in frozen-head
adapter that avoids the CE regression below. This older failure remains evidence.
The subsequent [solver/trajectory follow-up](SOLVER_TRAJECTORIES.md) adds
suggestion harvesting, intermediate-step losses and an explicit token counter.

Research and measurements: 2026-09-22. This extends the
[kernel/refactoring research](KERNEL_REFACTORING_RESEARCH.md), not a claim to
implement every Lean transformation or find globally shortest proofs.

The important change is that the autoencoder can now learn **replacement edits**,
not just retain/delete source operations. The reduction catalog now has 30
families. A separate finite Boolean affine-invariant miner is also available.

## What changed

| Component | Implemented | Boundary |
| --- | --- | --- |
| `rewrite_policy.py` | Mine bounded span templates with local-identifier copy slots; learn a softmax over identity and applicable template/location pairs | Lexical source spans, not typed Lean ASTs |
| `autoencoder_training.py` | Opt-in edit-head CE and expected cosine-loss gradients, checkpoint persistence, ablations and coverage gates | Existing operation/latent heads still have their own losses |
| `rewrite_distillation.py` | Compile source and shorter teachers, train only on training rows, freeze weights, independently decode and compile evaluation predictions | Small generated structural-transfer curriculum |
| `router_tuning.py` | `--train-rewrite-policy`; prepare verified training grammar before taking loss baselines; rollback on metric regression | Default remains off; no automatic production promotion |
| `logic_refactor.py` | Terminal local-alias reduction and redundant symmetry reduction | Proposals require Lean admission; not arbitrary substitution |
| `affine_invariants.py` | GF(2) nullspace mining over bounded reachable Boolean states, then Houdini initiation/preservation checks | Explicit finite models, currently at most four state bits; not integer/polyhedral analysis |
| `evaluate_rewrite_checkpoint.py` | Frozen model-only arena evaluation, zero-edit-weight and untrained comparisons, exact statement binding and strict axiom audits | Local regression, not an official arena score |

The existing catalog also includes propositional algebra, K-map/Quine–McCluskey,
DNF/CNF, ROBDDs, bounded propositional equality saturation, proof slicing,
context/invariant reductions and Lean/Mathlib tactic proposals. Their different
trust and applicability boundaries remain documented in the earlier report.

## Why an edit head

The older sparse decoder could choose a subsequence of source operations. That
cannot learn `exact h` to `assumption`, or a constructor proof to a compact term,
even when the operation classifier assigns the target a better probability.
Improving teacher-forced loss alone did not establish shorter rendered proofs.

The new head first mines templates from verified training pairs. Local names
inside a matched span become copy slots. At inference, it enumerates applicable
locations using the source alone and scores them with learned sparse features:
rule identity, neighboring tactic heads, first/last/nested position and a few
header-domain indicators. Identity is an explicit alternative and wins ties.
Zero edit weights therefore emit the unedited body, even with the learned
template bank present. No teacher target, compiler search or fallback repair is
used inside this decoder.

This is a learned selector over a symbolic grammar, **not** a neural generator
that discovers arbitrary tactics. Rules are extracted from examples; their use
is learned. Copy eligibility is lexical, not a scope/type proof. Every rendered
proposal must still be compiled under the original theorem and environment.

Bounds are explicit: 64 templates, 64 choices per decode step, eight lines per
changed span, 16 copy slots, 256 input body lines, and at most eight edit steps
(four by default). Pure insertions, oversized changes and opaque/commented
bodies abstain. Hostile command forms are rejected. Unsupported target labels
return unavailable edit loss, not an invented identity label or zero loss.

## Objectives and admission

For source-only edit choices `j`, let `p_j = softmax(w · features_j / T)`. The
edit objective is label-smoothed target cross-entropy plus
`lambda * sum_j p_j * (1 - cosine(op_bag_j, target_op_bag))`. Its gradient includes
`p_j * (cost_j - expected_cost) / T`, so the cosine term really affects edit
weights. Finite-difference tests cover several temperatures; an underflow test
checks that an extremely unlikely correct edit still gets a valid CE gradient.

Operation-sequence CE, edit CE, binding loss (if enabled), latent reconstruction,
token counts and proof validity remain separate diagnostics. The existing
reported cosine combines operation-bag similarity and hashed-feature latent
reconstruction. Neither component establishes semantic equivalence. Much of
the measured arena cosine improvement also survives zeroing edit weights;
it must not be attributed solely to the new edit.

Teachers are shorter only under a fixed token counter and must retain the exact
theorem envelope. The isolated runner requires both compiler success and an
accepted transitive axiom audit before training. It rejects missing/failed
audits. The low-level `prepare_rewrite_training()` API trusts its caller to
supply verified training-only pairs; it does not run Lean itself.

Grammar growth happens before taking edit-loss baselines. Saved operation
vocabularies are preserved; missing operations require explicit vocabulary
migration and rebaselining. Fresh models now include `symm`, `let` and `skip`:
77 output classes including EOS. Old 49-class proxy numbers are not comparable
to this fresh-model CE baseline.

Canary gates reject operation/edit CE regressions, edit-cosine regressions,
nonfinite metrics, disappearing measured edit coverage and verification loss.
The source/target identity, compiler receipts, template bank and frozen state
digest are retained. Evaluation never substitutes a search winner for a failed
raw prediction. Shorter proofs do not override a failed metric gate.

NCA and Typesafe feedback remain auxiliary proposal/ranking signals, never
proof authority. This experiment neither trained an NCA nor called a live LLM.
Their existing router proposals can feed verified training pairs when enabled;
that broader integration has not been shown here to improve model compression.

## Measured learning experiment

The real Lean run used six training rows, 40 epochs and 240 updates, with a
learning rate of 0.15, decay over 1,000 steps and no warmup. Five mined templates
cover exact-local replacement, a terminal alias, constructor packing, symmetry
and conjunction projection. A `PLift p → p` projection is a negative control:
it must not be replaced by the superficially similar `simp_all` proof.

Each development/evaluation split contains six rows. Validation, canary and
holdout identifiers and source contents are disjoint from training, but are
mostly alpha-renamed instances of the **same structural families**. This is not
semantic-family decontamination or evidence of broad theorem generalization.
The final holdout is first compiled/scored after the checkpoint freezes; there
is no subsequent weight update or teacher-bank expansion.

| Split | Valid predictions | Shortened predictions | Total body tokens before → after |
| --- | --- | --- | --- |
| Validation | 6/6 | 5/6 | 28 → 12 |
| Canary | 6/6 | 5/6 | 28 → 12 |
| Final holdout | 6/6 | 5/6 | 28 → 12 |
| Same grammar, zero edit weights (each split) | 6/6 | 0/6 | 28 → 28 |

Canary operation CE fell **4.343805 → 0.919363**, edit CE **0.760725 → 0.152497**,
and reported cosine rose **0.157833 → 0.829083**. The runner made 64 unique
compile calls, including failed teacher proposals, under strict axiom audits.
The negative control remained valid and unchanged. All development and final
holdout gates passed. These figures describe tiny synthetic proofs, not arena
compression percentages or throughput.

## Frozen arena transfer and the failed gate

The checkpoint was then evaluated without training/search/repair on the frozen
`CallElimCorrect.substOldPostSubset` record and its historical 392-token seed.
The supplied 391-token reference was verified before inference and used only
for loss reporting, never as a decoder input or fallback. These are known local
regression inputs, not fresh arena canaries.

| Input | Untrained | Trained | Zero edit weights | Operation CE before → after | Gate |
| --- | --- | --- | --- | --- | --- |
| Frozen original | 482 | 481 | 482 | 4.343805 → 4.406696 | Reject |
| Historical best seed | 392 | 391 | 392 | 4.343805 → 4.310716 | Accept |

Both model outputs pass Lean 4.26.0 in pinned Strata commit
`451e5f047bafa010d178856db76c00029bfa4d7f`. Their target declarations depend only
on `Quot.sound` and `propext`, not `sorryAx` or native-decision axioms. This is
Lean's kernel/axiom audit, not a second independent kernel implementation.

The model learned to replace `exact ih` with `assumption` (selected probability
0.592051). It **matches the prior deterministic 391-token best; it does not beat
it**. The original-input CE regression is 0.062891, above the 0.02 allowance,
so this checkpoint is **not promoted**, despite valid token savings and better
cosine. This is evidence of narrow transfer and a generalization problem worth
addressing, not permission to relax the acceptance metric.

Arena edit-label CE is unavailable against the fixed reference: the original
needs out-of-bank changes; on the historical source the IR also canonicalizes
`intros` to `intro`, making exact span labels unavailable despite operation-level
exact match. `null` is reported, not zero. Blank-line/trailing-space normalization
is allowed in the restricted edit loss; alias-normalized edit supervision is
still a coverage limitation. Operation CE is nevertheless measured and gated.

The frozen 15-row dataset SHA remains
`6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804`.
Only the above arena theorem was measured in this model-only transfer run.

Saved artifacts:

- [Checkpoint](tests/fixtures/rewrite_distillation_checkpoint.json), state SHA
  `5fdd503e451f0e6f843ddf07ac0a3e6ccbe8e071a0b6eaabe374e6a60069a9cd`.
- [Compact measured evidence](tests/fixtures/rewrite_distillation_evidence.json),
  including synthetic outputs, axiom audits, ablations and the failed arena gate.
- [Earlier deterministic best](tests/fixtures/kernel_refactor_local_best.json),
  kept separate and unchanged.

## Research implications and next architecture

Verifier-filtered expert iteration supplies shorter proof pairs for supervised
training; it also distinguishes a search procedure's best output from a model's
single prediction. ProofOptimizer implements this at a much larger scale. Its
results do not establish the performance of this sparse model.
[ProofOptimizer](https://arxiv.org/abs/2510.15700).

Edit representations and incremental tree transformations motivate learning
changes rather than copying whole long proofs. Our bounded span-copy selector
is a first implementation of that direction, not a reproduction of their neural
architectures. A stronger successor should consume elaborated Lean expressions
and source spans, with typed local identities and binder-aware actions.
[Learning to Represent Edits](https://arxiv.org/abs/1810.13337),
[Learning Structural Edits via Incremental Tree Transformations](https://arxiv.org/abs/2101.12087).

Insertion/deletion models can change sequence length without a subsequence-only
decoder. This supports investigating a learned copy/insert/delete head, with
teacher trajectories and Lean admission retained. The present implementation
does not implement a Levenshtein Transformer or unrestricted insertion.
[Levenshtein Transformer](https://arxiv.org/abs/1905.11006).

Lean's `grind?` can suggest a restricted `grind only` call or script. Harvesting,
rechecking and distilling those explicit proofs could reduce solver search and
provide more diverse teachers. This was future work in this experiment;
the solver/trajectory follow-up implements bounded single-line harvesting.
Simply adding `grind` to a candidate list is not equivalent.
[Lean: minimizing grind calls](https://lean-lang.org/doc/reference/latest/The--grind--tactic/Minimizing--grind--calls/).

For invariant compression, GF(2) nullspace mining now finds parity relations in
explicit reachable Boolean states. A reachable-state affine hull need not be
inductive on its unreachable members, so Houdini rechecks preservation over all
modeled states. Tests include a counterexample to that inference. Lean
initiation/preservation obligations must still be proved. This is not Karr's
infinite-state affine analysis, a polynomial invariant engine or a general
program verifier.

Recommended next experiments, not claimed implementations:

1. Use a broader, provenance-grouped training corpus with preserved-proof replay
   to test whether it prevents the observed arena operation-CE regression.
   Keep new theorem families and final holdouts out of teacher mining/tuning.
2. Collect typed Lean `Expr`/InfoTree dependencies and solver suggestions, then
   train span/AST edit trajectories with coverage and failure/abstention targets.
3. Evaluate learned policies and search separately across all supported frozen
   records and new canaries. Track source tokens, elaborated proof DAG size,
   heartbeats and end-to-end compile cost; a shorter script may be slower.
4. Explore proof-reconstructing scoped e-graphs and certificate-backed
   infinite-state invariant domains. Keep Python finite-model truth tables,
   fuzzy scores and ML kernels outside the trusted proof base.

## Reproduction

From the repository root, using an available Lean installation:

```bash
python -m jevops.rewrite_distillation --epochs 40 --output /tmp/jevops-distillation-new.json
python papers/completion/lean_refactor_arena/harness/evaluate_rewrite_checkpoint.py \
  --checkpoint tests/fixtures/rewrite_distillation_checkpoint.json \
  --name CallElimCorrect.substOldPostSubset \
  --reference-fixture tests/fixtures/kernel_refactor_local_best.json \
  --output /tmp/jevops-model-only-arena-new.json
python -m pytest -q tests/test_rewrite_policy.py tests/test_rewrite_distillation.py \
  tests/test_rewrite_checkpoint.py tests/test_affine_invariants.py
```

Choose unused output paths; the runners refuse to overwrite receipts. Arena
evaluation needs the existing pinned project/toolchain cache and denies network
access. Do not run concurrent splices against the same cached project. Its
`ok` field means kernel-valid evaluation; always inspect `metric_gates_accepted`
as well. Neither runner promotes a checkpoint or writes production memory.

Validation on 2026-09-22: the full suite passed **290 tests** with
`JEVOPS_MATHLIB_PROJECT` set to the available pinned Mathlib project. After
adding the explicit recorded-arena CE-rejection regression, all **four focused
checkpoint tests** passed. The one warning is a pre-existing deprecated import
in the optional `ipfs_datasets_py` integration. The frozen dataset digest and
clean cached Strata worktree were checked again after arena evaluation.
