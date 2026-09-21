# Lean IR autoencoder training protocol

This repository now treats text → Lean IR → text as a measurable training
pipeline rather than a Jev-only ranking heuristic.

## Trust order

1. The Lean/Lake consumer is the proof authority.
2. The canonical IR parser/renderer is the syntax boundary. It preserves
   theorem binders, goals, operation order, and bounded arguments; it rejects
   `sorry`, `admit`, command smuggling, and unknown operations.
3. TypeSafe and Jev are soft decision/reward signals. They may rank candidates
   or supply uncertainty, but cannot admit an unverified candidate.
4. Cosine similarity, cross-entropy, length, and reconstruction metrics are
   training/diagnostic signals. None is a proof.

## Objective

`LeanIRAutoencoder` uses a JSON-safe sparse model with fixed hashed feature
and latent dimensions. Each teacher-forced operation step contributes

* label-smoothed categorical cross-entropy;
* a clipped sparse SGD update to operation, feature, and transition heads;
* a latent reconstruction update whose quality is reported with cosine
  similarity;
* KL/length/reward terms in the normalized objective report.
* an optional NCA auxiliary reward from cell energy, neighborhood state,
  residual help/unsafe, contrastive history, and verifier outcomes;
* an optional TypeSafe fuzzy-plausibility reward, never treated as proof;
* a relative minimality reward for reducing Lean token/IR-operation size.

Learning rate uses warmup, cosine decay, gradient clipping, weight decay, and
plateau reduction. The model state is bounded by the feature bucket count and
does not retain corpus text. Disjoint streaming workers can merge their
bounded sparse checkpoints with `merge_model_states` without centralizing the
trillion-token corpus.

## Evaluation protocol

`build_canary_manifest` creates content-addressed, deterministic `train`,
`validation`, `canary`, and `holdout` assignments. Duplicate source digests
are kept in one split. The validation split chooses the best checkpoint; the
canary is only a regression gate. `train_autoencoder` never evaluates the
holdout. `train_autoencoder_stream` additionally accepts a split-aware factory
and never requests the holdout stream. Its streamed metric/verifier work is
bounded by default while full stream counts remain observable. Use
`evaluate_frozen_holdout` only
after the model/configuration is sealed; its result explicitly forbids later
tuning.

## Research lineage and limits

The design follows the sibling `ipfs_datasets_py` modal-autoencoder work:
separate CE/cosine/reconstruction metrics, normalized objective components,
sparse/batched updates, learning-rate safeguards, and custodian-blind holdout
gates. The NCA integration follows this repository's energy/neighborhood
cells and writes bounded verifier feedback back to the autoencoder skill cell.
TypeSafe can assess fuzzy theorem plausibility with typed Choice/Score/Noul
questions, but it is explicitly not a sound theorem prover. It does not claim
that a 256-bucket portable model is sufficient for
trillions of Lean tokens or that proxy metrics predict a Lean Refactor Arena
score. A production run still needs a pinned Lean corpus, a real Lake-backed
paired benchmark, sharded storage, and an independently sealed Arena
holdout. The portable implementation is the correctness and experiment
contract those faster backends must preserve.

For shortest-proof experiments, `refactor_smallest` generates bounded
deterministic shrink probes before stochastic IR perturbations. With a Lean
compiler supplied, it selects only among verified candidates and makes proof
body token count the primary objective; TypeSafe, NCA, cosine, CE, and other
rewards are tie-breakers or learning signals. This prevents a soft reward from
choosing an invalid or longer proof. The four-problem regression and its
frozen local pre-shrink baseline live in
`tests/test_autoencoder_rounds.py` and
`tests/fixtures/autoencoder_smallest_baseline.json`.

The optional `RouterTuningLoop` adds an LLM proposal layer through
`ipfs_accelerate_py.llm_router` (default `codex_cli` / `gpt-5.6-luna`). Its
JSON plan is parsed into an allowlisted tactic/IR vocabulary; the model cannot
write files or admit proofs. Local MCA/PCA tactic families are expanded beside
the router proposals, all candidates are compiled once with a cache, and only
the shortest verified result becomes a positive autoencoder target. Failed
router candidates still produce bounded negative NCA/verifier feedback, so
the loop learns which tactic families are unsafe without treating an LLM
confidence score as theorem evidence.
