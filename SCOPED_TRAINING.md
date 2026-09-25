# Scope/type-guided teacher discovery

`jevops.scoped_proposals` searches native InfoTree **before-contexts** for a
shorter local term. `jevops.scoped_training` feeds only replayed, whole-proof
admitted outputs into the existing trainable graph edit-policy fitter. Both are
opt-in; this does not alter the production outer loop or existing benchmarks.

## Search and trust boundary

The bounded grammar covers local references, curried applications and nested
applications, including dependent and implicit arguments. It uses native free
variable identities and observed type DAGs, not lexical guesses about binders.
Type matching erases binder names and metadata in a separate hash-consed search
graph, preserves variable identities, universes and binder annotations, and uses
capture-avoiding de Bruijn substitution. Shared subgraphs are not expanded into
trees. Implicit applications use explicit `@` syntax when necessary.

Default limits: three application nodes per term, 128 generated terms, 16,384
type comparisons, 64 locals and 32 inspected closing events. Search reports
truncation separately from absence of a match. Unsupported multi-goal contexts,
term/universe metavariables (even solved ones), non-default locals, ambiguous
shadowed names and inaccessible spellings abstain. Structural matching does not
perform definitional equality, beta/delta reduction, coercion insertion or
typeclass synthesis. It can miss valid shorter terms.

This graph is **not** the lossless [expression codec](EXPR_DAG_CODEC.md), a Lean
unifier or a proof certificate. An observed type match only generates a proposal.
Source/exporter/environment/trace bindings are checked before search. Then the
[native replay collector](PROOF_REPLAY.md) regenerates the original context,
checks baseline and proposed closing proofs, replaces exactly the observed UTF-8
span, and applies the whole-source type/axiom/token/expression-cost/IR gates.
No later alias is moved into a context where its free variable is unavailable.
Local replay success cannot override a failed whole-source gate.

To inject this proposal generator into an existing collector:

```python
from functools import partial
from jevops.scoped_proposals import scoped_proposals

proposal_fn = partial(scoped_proposals, environment_sha256=environment_sha256)
# Pass proposal_fn to collect_replay_pairs or replay_distillation.run_experiment.
# propose_scoped(...) additionally returns the bounded search diagnostics.
```

## Bounded learning control

```bash
python -m jevops.scoped_training \
  --project-root /path/to/core-project \
  --environment-sha256 "$DEPENDENCY_MANIFEST_SHA256" \
  --epochs 40 --seed 17 --output-dir /path/to/new-scoped-run
pytest -q --test-seal=off tests/test_scoped_proposals.py tests/test_scoped_training.py
```

Use `--lake` for an appropriate Lake project. The environment fingerprint is
caller-owned: a hash alone does not authenticate transitive dependency closure.
Native Lean/imports and compiler/replay callbacks remain trusted infrastructure.

The four built-in cases are explicitly **inspected training/regression motifs**:
hypothesis reuse, unary application, dependent application and implicit dependent
application. They are not random canaries or a decontaminated benchmark. The
runner never reads supplied validation/canary/holdout contents. It stops before
fitting unless every training source obtains an admitted shorter teacher.

The existing fixed learning-rate/pooling/update grid selects using training
edit-choice cross-entropy plus expected IR-operation cosine loss, with losses
also reported separately. The graph encoder is updated. Reconstruction heads
and an NCA are **not** trained here. Cosine is not semantic equivalence, and
these metrics must not be reported as reconstruction CE/cosine. The learned
decoder still proposes lexical template edits; it is not type-safe by
construction. Adding this teacher search does not implicitly mask inference
choices by type. Raw selected training outputs undergo the whole-source gate
without candidate repair or teacher substitution.

## Generated evidence

The command writes `experiment.json` (search/native receipts, checkpoints and raw
predictions), `measurement.json` (small derived metrics) and `summary.md` directly
to a new directory. It prints only a short status. Existing output directories
are never replaced. No report or checkpoint is authored through model text.

The first native Lean 4.34.0 control, seed 17 / 40 epochs, admitted all four
teachers and checked all four raw model outputs: 44 proof-source tokens became
12, with non-growing unique/expanded proof-expression counts and no new axioms.
Training CE was 0.69314718 -> 0.05610357 and expected IR-operation cosine loss
0.24390655 -> 0.00420145. This used eight distinct whole-source compilations and
four native replay calls; per-run memoization reused identical compiler inputs.
The selected `multiscale_online_0.25` arm made 160 updates. Full receipts are
generated at run time, not copied into this document.

These are training-fit/plumbing results, not a learned compression advantage,
global minimum, arena high score, throughput estimate or fresh held-out result.
There is no promotion. Evaluation against a frozen, contamination-controlled
manifest and a same-budget symbolic baseline is a separate stage below. JeV fuzzy
feedback can remain auxiliary; it cannot replace native teacher admission.

## Frozen transfer evaluation and matched-choice controls

`jevops.scoped_evaluation` loads the **existing** frozen training artifact; it
never fits, mines templates, changes learning rates or calls the teacher search.
It compares the selected learned encoder, the saved fixed-feature policy, and a
non-learned token-length selector. All use exactly the same training-mined grammar
and get one raw candidate verification per source, with no alternate-candidate
search or rescue. Identity wins token-length ties. Native source checks are
shared; reference checks are separate. This matches the candidate-check budget,
**not** training compute, wall time or a comprehensive symbolic hammer.

```bash
python -m jevops.scoped_evaluation \
  --training-dir /path/to/completed-scoped-run \
  --project-root /path/to/core-project \
  --environment-sha256 "$DEPENDENCY_MANIFEST_SHA256" \
  --seed 20260923 --output-dir /path/to/new-frozen-evaluation
pytest -q --test-seal=off tests/test_scoped_evaluation.py
```

The command binds the frozen fit and saves `protocol.json` (manifest, fixed
budgets, seed and training hashes) **before** invoking Lean. Evaluation rejects
ID/family/source overlap, plus name-insensitive type/proof overlap with training
sources and admitted targets. All arms commit predictions for all rows before
any reference is used for loss calculation. No parameter updates follow labels.
Failed source/candidate checks stay in every sample denominator and earn zero
verified savings; missing, invalid or unreachable references fail loss coverage,
never become identity supervision. Compiler timeouts cannot trigger a solver
fallback. Complete coverage/validity/cost and CE/cosine nonregression are required
both in aggregate and in each partition, against both baselines.
Source-token growth independently fails the run even when expression-DAG cost
does not grow; a zero-savings clamp must not hide a length regression.

The six hand-designed transfer layouts use seeded local names. Their validation,
canary and holdout partitions share rewrite motifs with training; neither those
labels nor the structural-overlap guards imply mathematical-family independence.
After inspection, these cases are regression probes, not new blind trials.

The length baseline's logits are `-proof_source_tokens` at fixed temperature 1.
Its CE uses the same 0.02 label smoothing as the learned policies. These are
distributional edit-policy diagnostics: temperature changes their values, and
expected operation-bag cosine is neither semantic equivalence nor reconstruction
fidelity. This protocol does not tune the temperature or relax either loss gate
after viewing results.

### First native result: preserved failure, not a compression advantage

The existing seed-17 / 40-epoch checkpoint, evaluated once on the seed-20260923
manifest using Lean 4.34.0, produced six valid, cost-safe outputs. Every arm chose
the same bodies: **69 -> 27 source tokens**, saving 42. All six references had
measured losses. There were 11 distinct native whole-source compilations.

The learned policy improved aggregate CE/cosine relative to both baselines, but
failed cosine nonregression against the token-length baseline in the canary and
holdout partitions. Accordingly **the overall evaluation failed**. Identical
argmax edits can still have different expected cosine because the policies place
different probability mass on the other choices. This is not a native proof
failure, and the aggregate improvement does not erase the per-partition failure.
No checkpoint was changed or promoted, and no arena/high-score claim is made.

The [generated summary](tests/fixtures/scoped_evaluation_control/summary.md) and
[compact measurement](tests/fixtures/scoped_evaluation_control/measurement.json)
preserve this result. They are historical observations, not fresh proof authority.
Full runtime receipts remain in the evaluation directory's `evaluation.json`.

To regenerate only compact reports without Lean, training or a new evaluation:

```bash
python -m jevops.scoped_evaluation \
  --training-dir /path/to/completed-scoped-run \
  --environment-sha256 "$DEPENDENCY_MANIFEST_SHA256" \
  --report-from /path/to/frozen-evaluation/evaluation.json \
  --output-dir /path/to/new-compact-reports
```

Both input bindings are checked. Reports are generated directly to files; stdout
contains only a short status. Existing outputs are refused. Report-only exit code
zero means rendering succeeded even when the recorded evaluation failed.

## Competing-choice training follow-up

The [native-rejection control](NATIVE_REJECTION_TRAINING.md) audits competing
training rewrites and adds an optional rejected-probability penalty without
changing CE/cosine. Its three learning-rate runs preserve a useful failure:
the graph policies avoid invalid candidates but still miss two shorter admitted
teachers. These training results do not replace the frozen evaluation above.
