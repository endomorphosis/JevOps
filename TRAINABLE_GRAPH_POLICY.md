# Trainable source-DAG edit policy

`jevops.graph_policy` implements an optional, bounded CPU/float64 structural
proposal model. Unlike the fixed-neighborhood encoder in `structural_policy`,
constructor/payload/binder embeddings and ordered message-passing matrices receive
actual gradients. This is an edit policy, **not** a trained lossless graph
autoencoder, and its copy decoder is **not** type-safe by construction.

## Representation and prediction

The input is a fresh compiler export of the original proof and declared type.
`GraphContext` binds immutable DAG bytes to the source, environment and toolchain.
Factory admission reuses `structural_training._checked_export`: exact supported
expression round trip, native kernel check, axiom audit and artifact bindings.
Callbacks/environment fingerprints are trusted infrastructure; hashes are not
signatures and full dependency closure remains unauthenticated.

The encoder preserves ordered child roles, binder annotations, de Bruijn relative
indices and edges entering binder bodies. It pools proof/type roots and their
reachable unique nodes separately. Bound-variable sharing is storage sharing,
not evidence that occurrences refer to the same local. This is not complete
binder-environment unfolding or a proof of alpha/semantic equivalence. Binder names
and source/theorem IDs are excluded; constructor payloads include hashed constant,
literal and universe information. Hashing and dense embeddings remain lossy.

Graphs are validated as closed and canonically numbered, then bounded to 4,096
expression/universe nodes and 1 MiB context bytes. Tensorization/message passing
visits DAG nodes/edges, not expanded tree occurrences. Width, rounds, candidates
and checkpoint tensor shapes are bounded; there is no pickle checkpoint loader.

The decoder uses the existing finite, single-step lexical edit/copy grammar.
Only verified training improvements mint templates. Inference sees no target DAG
or teacher, invokes no solver, and does not compile alternatives. Identity wins
initial zero-readout ties. Every emitted refactor remains a proposal requiring
whole-proof checking. A truly typed-by-construction edit decoder is still future
work; training on typed sources does not establish that property.

## Training objective and trust boundaries

The objective is edit-choice cross entropy (label smoothing 0.02), plus 0.35 times
expected tactic-operation-bag cosine loss. Cosine is a diagnostic proxy, not a
semantic equivalence check. This does not replace the existing autoencoder's
sequence/reconstruction objective; that model and the production outer runner
are unchanged by the isolated experiment.

An optional JeV path adds `-weight * E[utility] + beta * KL(policy || reference)`.
Utilities must cover the same candidate set, lie in [-1, 1], and be bound through
the existing scorer/rubric receipt protocol to the exact source, DAG, grammar,
model weights and update step. Reusing feedback after an update is rejected.
Reference logits are detached; callers pin the reference checkpoint. CE/cosine
remain present. No scorer or hosted provider is selected automatically, and
neither Lean nor a black-box JeV call becomes differentiable. A fuzzy score can
teach selection but cannot admit a proof or create a verified teacher.

Training updates are train-only, globally gradient-clipped, and committed only
after all parameter updates pass finiteness/range checks. Evaluation never updates
weights. Low-level training APIs assume admitted targets; use the experiment's
verified-pair boundary rather than passing arbitrary model-generated labels.

## Reproducible control experiment

Install the optional extra (`pip install -e '.[graph]'`) if PyTorch is absent.
The repository remains usable without importing or installing PyTorch.

```bash
python -m jevops.graph_experiment \
  --project-root /path/to/pinned/lean/project \
  --environment-sha256 YOUR_ENVIRONMENT_FINGERPRINT \
  --epochs 80 --threads 1 \
  --output-dir /path/to/new/output-directory

python -m pytest --test-seal=off -q \
  tests/test_graph_policy.py tests/test_graph_experiment.py
```

Use `--lake` for a Lake project. Output directories must be new. `run.json` contains
predictions, checks, losses, checkpoint hashes, toolchain/runtime identities and
bounded compile receipts; `summary.md` is rendered by deterministic code.
Native tests are always fresh, not sealed pytest passes.

Arms share the training rows, template bank, one-edit budget, update count and
learning-rate schedule: lexical, fixed graph, learned graph, frozen encoder, and
learned node-only features (zero message-passing rounds). Neural parameter counts
differ from sparse counts and are reported. Drop-graph and zero-weight diagnostics
are not independently trained baselines. Source compilations are shared across
arms and counted; receipt reuse within the run is not another independent check.

All models freeze before evaluation. Raw predictions are committed before reading
evaluation labels, then checked without teacher repair. Scoring requires matching
declared types/universe parameters, no additional axioms, strict source-token
savings and non-growing unique/expanded expression-node counts. Invalid/unverified
outputs receive no savings. Original reconstruction heads are untouched.

Default splits are renamed reflexivity controls, not structurally independent
holdouts. A completed run never promotes a checkpoint or claims an official arena
score. Once inspected, evaluation cases are regression probes, not fresh final
tests. Independent theorem/repository/structural-family splits, broader rewrites,
typed decoding, learned NCA/critics, and throughput work remain follow-up tasks.

## Training-only refinement and frozen transfer

`graph_refinement` now investigates the failed control without tuning on its
evaluation labels. It measures layer-by-layer training embedding separation,
compares a fixed small grid of pooling/update/learning-rate choices, and chooses
by training teacher-choice accuracy, then mean CE-plus-cosine objective.
The old last-layer policy and v1 checkpoint format remain unchanged by default;
the historical failed experiment still replays. Multiscale checkpoints use v2
and retain the constructor embeddings and every message-passing layer at readout.

`GraphEditPolicy.train_batch` takes bounded, training-only admitted examples,
averages their losses before global gradient clipping, and commits the whole
update atomically. It rejects mixed training/evaluation batches before reading
labels. Gradients reach all retained layers. Finite differences and order-invariant
batch-update tests cover the implementation. The existing single-example JeV
path remains available; this experiment does not call JeV or train an NCA.

The fixed grid uses last/multiscale pooling, online/batch updates, and learning
rates 0.05/0.15/0.25, with frozen-encoder, node-only and fixed-feature controls.
All arms see 80 passes over the same two training examples. Online arms perform
160 updates; batch arms perform 80. Learning-rate decay is indexed by consumed
examples. Parameter and update counts differ and are reported: this is not a
compute-matched claim of neural superiority.

```bash
python -m jevops.graph_refinement \
  --project-root /path/to/pinned/lean/project \
  --environment-sha256 YOUR_ENVIRONMENT_FINGERPRINT \
  --epochs 80 --seed 17 --transfer-seed 20260923 \
  --output-dir /path/to/new/output-directory

python -m pytest --test-seal=off -q \
  tests/test_graph_policy.py tests/test_graph_experiment.py tests/test_graph_refinement.py
```

The runner persists `training.json`, including selection/checkpoints and a freeze
hash, **before generating** transfer cases. `evaluate_frozen` validates the
receipt, reconstructs read-only model copies, checks disjoint family labels and
binder-name-insensitive proof/type hashes, and commits every arm's predictions
before reading each target. Labels cannot update the policy. Raw outputs pass
the same native type/axiom/expression-cost gates, without teacher repair.
`evaluation.json` and a deterministic `summary.md` report aggregate and per-split
results. Missing loss/cost coverage fails closed. Validity, cost coverage, token
savings, CE and cosine must pass aggregate **and each split**; aggregate savings
cannot hide a holdout regression. Hashes are bindings, not signatures.

Transfer cases use successor congruence, function application, product projection
and list-constructor goals. Their labels and type/proof shapes are disjoint from
training, but they still share the alias-to-`rfl` task. This is a structural-layout
transfer probe, not independently decontaminated mathematics or the arena corpus.

## First native result: rejected, not promoted

The first 80-epoch, seed-17 run on Lean 4.34.0 and PyTorch 2.13.0 made 16
deduplicated native compiler calls. A compact machine-generated receipt is kept
in `tests/fixtures/trained_graph_control.json`; it binds the full run by SHA-256.

The learned encoder genuinely changed, but selected `rfl` for both the reflexive
and non-reflexive equality controls. Lean rejected the latter. Its evaluation
validity was **1/2**, compared with **2/2** for fixed graph features. Both saved
16 verified source tokens; the failed prediction contributed zero savings.
Mean edit CE fell only from 0.693147 to 0.691502 and expected cosine loss from
0.5 to 0.499115. The fixed-feature arm reached 0.360834 and 0.296826 respectively.
The node-only arm also reached 2/2 validity, without additional savings.

Thus real gradient flow is established, not better proof compression. The gate
fails on every split and nothing is promoted. These inspected cases are now
regression probes. The next training-only investigation should test whether
message passing attenuates discriminative binder-index features; this is a
hypothesis, not an established diagnosis. Model/learning-rate changes must use
development evidence, followed by structurally independent fresh evaluation.

## Refinement result: better validity, still not promotable

The first native refinement selected **multiscale batch updates at learning rate
0.15** using training data only. Radius-zero training-pair L2 separation was
0.172905; after two message-passing layers it was 0.037198. Relative separation
remained approximately 0.034, so this does not establish oversmoothing. Batch
updates corrected the two training choices; multiscale retention improved mean
training CE to 0.659995 and cosine loss to 0.482790. These ablations change update
count/clipping behavior too, so they do not isolate one universal failure cause.

On eight post-freeze transfer cases, the selected model produced **8/8 valid
outputs** versus the old model's **4/8**, and saved 48 verified tokens, tying the
fixed-feature baseline. However, selected aggregate CE/cosine were
0.676686/0.491486 versus fixed-feature 0.629833/0.463424. On the four holdout cases
specifically, selected savings were **16 versus 32** for fixed features. The
selected model missed a valid projection shortening; extra canary savings hid
that deficit in the aggregate total. This motivated explicit per-split gates.

The model is rejected; there is no promotion, arena score, or extra-compression
claim. The frozen-encoder control also achieved 8/8 and 48 tokens, so the data do
not establish an advantage from learning encoder weights. Native compilation
used 3 deduplicated training calls plus 16 evaluation calls on Lean 4.34.0. A
compact generated measurement record preserves the result and full-artifact
hashes in `tests/fixtures/graph_refinement_control.json`. Gate/report replay of
those native observations is not another fresh evaluation. These inspected
cases are now regression probes; future model changes need fresh final cases.

## Multi-rule curriculum: verified teachers, shared grammar

`graph_curriculum` expands the two-choice control without modifying its old
checkpoints, the production outer runner, or the reconstruction autoencoder.
Five training-only pairs mint four templates: copy through an alias chain,
replace an alias chain with `rfl`, combine `apply f; exact h` into `exact f h`,
and eta-reduce `intro h; exact f h` to `exact f`. Non-reflexive equality now has
a shorter copy target instead of an identity label. These are lexical proposals,
not universally valid rewrite axioms; copying and `rfl` compete in the same
grammar and all predictions still require Lean.

The fitter admits both endpoints through the existing native type, universe,
axiom, IR-roundtrip, strict source-token and non-growing expression-node gates.
`grammar.json` records admitted training origins, candidate counts, and a shared
template hash across every arm. No evaluation target mints a rule. Teacher
optimality is not established, and the decoder still has a one-edit budget.

```bash
python -m jevops.graph_curriculum \
  --project-root /path/to/pinned/lean/project \
  --environment-sha256 YOUR_ENVIRONMENT_FINGERPRINT \
  --epochs 80 --seed 17 \
  --output-dir /path/to/new/output-directory

python -m pytest --test-seal=off -q tests/test_graph_curriculum.py
```

The runner saves selection/checkpoints and grammar before generating any transfer
cases. `--frozen-fit /path/to/training.json` reuses a trusted, hash-checked training
receipt with no updates; the environment must match. Epoch/model/training seeds
are ignored in that mode. A new output directory is still required. Invalid
evaluation protocols leave `failure.json`, exit nonzero, and do not create a
successful evaluation report. Valid evaluations emit full receipts, a compact
`measurement.json`, and a short deterministic `summary.md`. Reports neither run
Lean again nor grant proof authority to saved receipts.

The seven transfer layouts cover introductions, nested application, a Boolean
branch, prefixed eta reduction, beta equality, an order hypothesis, and negation
application. They share training motifs; their disjoint family labels and
name-insensitive declared-type/proof hashes are **not** semantic decontamination.
Changing the random seed only renames these layouts. After inspection they are
regression probes, not fresh final holdouts.

### Native multi-rule result

The initial manifest was rejected before scoring: moving a binder into `intro`
did not change the training theorem's declared type. The introduced-chain probe
was corrected to have an additional proposition/hypothesis. The exact persisted
training receipt and all checkpoints were reused unchanged for evaluation; no
model or rule tuning used transfer outcomes. This was a protocol correction,
not a successful first-run benchmark.

With 80 epochs and model seed 17, training selected `multiscale_online_0.25`.
All five training targets were selected correctly. Training edit CE fell from
0.936426 to 0.070716 and expected cosine loss from 0.416415 to 0.006567. The
selected encoder changed, with 400 examples/updates; batch controls used the
same 400 examples but 80 updates, so this is not compute-matched comparison.

On the corrected seven-case transfer probe, every arm produced seven valid,
non-growing proofs and saved **66 proof-body source tokens (101 → 35)**. The
selected arm's edit CE/cosine loss were **0.075375 / 0.003661**, versus fixed
features **0.186836 / 0.089421**. All aggregate and per-split gates passed.
The frozen encoder, node-only arm, and old last-layer architecture also saved
66 tokens. This supports learning teacher choices with lower proxy losses; it
does **not** establish more compression from learning a graph encoder. The
old-layer arm even had slightly lower aggregate CE (0.074383); evaluation did
not reselect the winner. Comparing 66 with the earlier experiment's 48 would be
invalid because both the grammar and evaluation cases changed.

The completed measurement used 10 training plus 14 evaluation deduplicated
compiler calls on Lean 4.34.0 / PyTorch 2.13.0. The abandoned protocol probe made
an additional source check. The standalone `Init` control uses a synthetic
environment fingerprint; full dependency-closure authentication remains absent.
Compact generated observations and the 24-line report are retained in
`tests/fixtures/graph_curriculum_control.json` and `graph_curriculum_summary.md`.
The passing probe does not promote a checkpoint or provide an arena/high-score
claim. No NCA, fuzzy critic, sequence reconstruction head, or lossless neural
codec was trained in this experiment.

## Checked composition of adjacent edits

`graph_composition` now runs a bounded sequence of proposals, rebuilding the
source DAG after every accepted edit. Each step must preserve the original
theorem envelope, declared type, universes, toolchain and axiom boundary, reduce
proof-body source tokens, and not increase unique/expanded expression nodes.
The runner tries only the policy's raw choice: it neither searches alternatives
nor repairs an output with a teacher. A later failed proposal ends the path and
earns **zero** saved-token credit for the whole rollout. The safe prefix and
failed raw proposal remain in the receipt for diagnosis.

Three training-only adjacent edges (alias copying → application → eta reduction)
join the five existing pairs. Native admission still precedes training, all
eight rows use the same four-template grammar, and no terminal identity label
is invented as proof of optimal stopping. This is teacher-forced one-step
supervision at intermediate states, not differentiation through Lean or an
end-to-end sequence autoencoder. The production autoencoder/NCA are unchanged.

The CLI freezes and saves training before creating its evaluation rows. The six
hand-designed layouts use conjunction branches, a disjunction injection, an
extra implication, an iff projection and pointwise quantified application.
Their lexical grammar coverage was preflighted during fixture development, so
they are **control probes, not blind final holdouts**. No evaluation losses or
predictions chose the grammar, training configuration or checkpoint. The old
inspected transfer set was not relabeled as training. New layouts still share
training motifs; changing seeds only changes names.

```bash
python -m jevops.graph_composition \
  --project-root /path/to/pinned/lean/project \
  --environment-sha256 YOUR_ENVIRONMENT_FINGERPRINT \
  --epochs 80 --max-edits 3 \
  --output-dir /path/to/new/run
```

The first native run selected `multiscale_online_0.25` on training data alone:
8/8 training choices correct, 640 examples/updates, and training CE/cosine loss
0.895880/0.324756 → 0.068506/0.005720. The trainable encoder changed. Batch arms
used 80 updates over the same examples, so this is not compute-matched training.

All six composed outputs and their intermediate edits passed native checks.
On the **same cases and weights**, one edit saved 90 source tokens; three edits
saved 114 (169 → 55 total proof-body tokens). The fixed-feature and frozen-encoder
controls also saved 114, demonstrating a composition benefit, not a neural
compression advantage. Selected adjacent-edit CE/cosine were 0.065184/0.002120
versus fixed features 0.089717/0.008837, passing aggregate and each split's gates.
These losses use all 18 checked teacher edges, averaged within each theorem,
then across theorems. They are not on-policy sequence/reconstruction losses;
one/composed arms have identical losses because they share weights and labels.

The run used 14 training and 24 evaluation deduplicated compiler callbacks,
Lean 4.34.0 and PyTorch 2.13.0, with the same synthetic standalone environment
fingerprint limitations as the earlier controls. The edit limit is not a claim
of convergence or globally shortest proofs. Nothing is promoted, and these are
not arena scores or gains over the earlier experiment's different cases.

## Generate reports directly on disk

Training runners write full receipts and compact generated summaries themselves.
To regenerate reports from a saved graph refinement/curriculum/composition run,
without printing or routing the large payloads through a language model:

```bash
python -m jevops.graph_reports \
  --input-dir /path/to/run \
  --output-prefix /path/to/reports/experiment
```

This validates receipt hashes, writes `experiment_control.json` and
`experiment_summary.md`, and prints only a small status object with filenames.
`--overwrite` explicitly permits replacing those two generated files; the
default refuses existing outputs, symlinks and directories. This performs no
training, Lean verification, or checkpoint promotion. Successful rendering does
not mean an evaluation passed: the short status reports `evaluation_ok` separately.
Composition report ordering is stable across JSON serialization/reloading.

The generated native record and short report live in
`tests/fixtures/graph_composition_control.json` and `graph_composition_summary.md`.
