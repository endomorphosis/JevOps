# Source-DAG-conditioned edit selection

The experimental `structural_policy` head now trains on fixed features of the
original Lean proof/type DAG. `structural_ablation` compares it with the existing
lexical edit features, using the autoencoder's train-only template grammar and
the same CE/expected-cosine objective. This is a separate opt-in, single-step
research path. Existing autoencoder checkpoints and production/router behavior
are unchanged.

## What is learned

The feature extractor computes ordered child-neighborhood labels at radii zero
through four, hashing into 64 buckets per block. Proof and declared-type roots
have separate normalized histograms and root-label blocks. It visits shared
nodes, not an exponentially expanded proof tree. A fixed per-example L2
normalization needs no training/evaluation corpus statistics.

Tags, binder annotations, bounded de Bruijn indices, let flags, projection-index
buckets and universe structure contribute to the labels. Constant/binder/
universe-parameter names, literal values, metadata contents, theorem IDs and
source hashes do not enter the feature vector. Raw hashes identify receipts,
not classifier inputs. Renaming fixtures therefore cannot supply a hidden label.
These deliberately lossy features can collide or conflate different semantics;
they do not prove equivalence or validity.

The learned score adds `rule × source-graph-feature` weights to each applicable
edit's existing lexical features. Identity remains the first, zero-score choice
and wins ties. Label-smoothed CE and expected operation-bag cosine loss have
actual gradients through the edit probabilities; finite-difference tests cover
both graph and lexical weights. Updates use clipped SGD, the existing learning-
rate schedule and identical budgets/order in both experimental arms.

Only this sparse readout is trained. The neighborhood encoder is fixed; this is
not a trained GNN, graph autoencoder, differentiable kernel or semantic embedding
guarantee. Operation/reconstruction parameters are frozen and their CE is reported
as unchanged, not improved. JeV and NCA are not used by this experiment.

## Inference and admission boundaries

A graph context comes from a source-bound, compiler-audited native export. It
pins the source digest, dependency fingerprint, Lean version/build, graph digest
and feature schema. Missing, stale, foreign-source, wrong-toolchain and malformed
contexts raise an error rather than silently falling back to lexical prediction.
The context class and compiler callback are trusted application interfaces;
neither a Python object nor a digest authenticates an untrusted producer.

Prediction sees only the original source, its context, the frozen grammar and
learned weights. It cannot read a target DAG, label, candidate check or teacher.
It performs **one edit**. Reusing the same graph after changing the source would
be stale; a future multi-step controller must re-elaborate each intermediate
source and account for that cost. It must not attach the final teacher graph to
earlier source states.

Source context preparation currently requires native Lean export. This adds
compiler overhead; no speedup, kernel-runtime reduction or trillion-token
throughput claim is made. Hashing is bounded by the codec's graph/payload limits.
Opaque imported definitions are not unfolded. Full dependency-closure
authentication and open proof-state contexts remain separate work.

The runner uses the [structural pair gate](STRUCTURAL_TRAINING.md) for compressed
training labels and independently checks identity sources. It freezes the shared
grammar before loss baselines, trains only training rows, then freezes both heads
before touching final holdout graphs/labels. Every emitted prediction is checked
in its unchanged theorem context, including type/axiom constraints and unique/
expanded proof-node non-growth. Invalid, unknown or growing outputs are reported,
never replaced by teachers or counted as verified savings.

The standalone model uses a new checkpoint schema and must be restored with
`StructuralEditPolicy.from_dict`, not loaded as a legacy autoencoder checkpoint.
Its low-level `train_step` remains a trusted supervised API, not a proof verifier.

## Measured experiment and limitations

See the [code-generated report](tests/fixtures/structural_feature_report/summary.md)
and full adjacent `run.json` for the native receipts, checkpoints and losses.
There are two training examples and two renamed examples in each evaluation
split. Both proofs contain three local aliases. The same lexical rewrite to
`rfl` is applicable to both, but only the reflexive equality supports it.
Non-reflexive examples have an explicit identity label; this does **not** mean
they cannot be shortened using some other tactic.

Both arms use the same grammar, one-edit limit and 80 epochs (160 updates each).
The structural head verifies both holdout predictions while the lexical head
verifies one. Both save 16 verified source tokens: **the demonstrated gain is
selectivity/validity, not additional compression**. Graph-weight removal and
all-weight removal emit identity on this fixture. Those are diagnostics of the
trained head, not substitutes for the independently trained lexical comparison.

The lexical baseline is intentionally the repository's existing shallow domain/
position feature set, which is identical for the two controls. This does not
establish superiority over stronger text encoders, explicit goal parsing or a
trained graph network. A node-bag-only comparison is also still needed to
isolate the contribution of the deeper neighborhood features. The final split contains renamed members of the same
structural family, not unseen mathematics. Replayed probes are regression tests,
not untouched holdouts. No arena result or checkpoint promotion is claimed.

## Running and checking

```bash
python -m jevops.structural_ablation \
  --project-root /path/to/project --lake \
  --environment-sha256 "$DEPENDENCY_MANIFEST_SHA256" \
  --epochs 80 --output-dir /path/to/new-experiment

python -m pytest -q tests/test_structural_policy.py tests/test_structural_ablation.py
```

Supply a caller-owned dependency manifest fingerprint for your project. The
archived small core experiment uses an explicitly synthetic fixture context
fingerprint and reports `dependency_closure_verified=False`; it is not a fully
authenticated environment manifest. Compilation is not a sandbox for imported
metaprograms.

The runner writes the long machine-readable receipt with code and a small fixed
report template, and refuses an existing output directory. Tests check gradients,
feature bounds/name invariance, context failures, checkpoint restoration, matched
grammar, holdout scheduling, exact experiment/report replay, and fresh native
proof checks on a deterministic renamed probe. Historical replay alone is not a
fresh kernel check.
