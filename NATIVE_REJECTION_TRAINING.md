# Native-rejection training and competing rewrites

This opt-in control adds complete, bounded candidate audits to graph edit-policy
training. It does not change production outer-loop wiring or overwrite the prior
[frozen transfer failure](tests/fixtures/scoped_evaluation_control/summary.md).

## Why add this control?

The previous scoped-training grammar offered just identity plus one shorter edit
on every compression case. The preservation case offered only identity. A model
selecting that sole edit cannot beat a shortest-text selector within the same
grammar. Changing confidence can change CE/expected cosine without changing the
chosen proof length.

`rejection_training.training_rows()` retains four **training** motifs and adds
balanced reflexive/nonreflexive Nat and Bool equalities with the same alias-chain
body. This creates competing `rfl` and `exact h` rewrites. Both can be valid for a
reflexive goal, but the shorter `rfl` fails on a general `n = m` goal even when a
hypothesis proves it. No evaluation examples or labels are imported into training.

## Admission, auditing and gradients

`candidate_audit.audit_candidates` checks every choice in the frozen training
grammar, including identity. Positive teachers first pass the existing native
whole-source type/axiom/token/expression-size/IR gates. Grammar mining uses only
those admitted teachers. The audit then requires complete choice coverage and a
teacher with minimum source-token length among its admitted choices. This is a
minimum in a finite grammar, not a global proof minimum.

Candidate outcomes remain distinct:

- `accepted` or `identity`: the native source/type/axiom/expression-cost checks passed;
- `elaborator_rejected`: a narrowly recognized, source- and position-bound Lean
  `rfl` failure—not a claim that the theorem is false;
- `cost_rejected`: a checked proof exceeds the permitted source/expression cost;
- `unknown`: timeout, missing/stale diagnostics, unsupported failure, or another
  unauthenticated/incomplete result. This stops the training control; it does not
  become a negative label.

The classifier deliberately recognizes only a small diagnostic family. Changes
in compiler wording can cause abstention. Native source/imports and compiler
callbacks remain trusted infrastructure; hashes are bindings, not signatures or
authentication of complete dependency closure.

`audited_loss` validates source, target, environment, toolchain, DAG, grammar,
candidate order, coverage and audit hashes before returning a differentiable
loss. The compared graph arms use identical initial weights and update budgets:

```text
standard = CE + 0.35 * expected_operation_cosine_loss
penalized = standard + 0.25 * probability_mass_on_rejected_choices
```

Label smoothing remains 0.02 in both arms. The audit mask is detached: gradients
flow through the policy probabilities, **not through Lean**. CE and cosine are
never disabled, and native audit metadata is not an inference-time oracle. Raw
training choices are measured against the same source-bound audited candidates;
there is no replacement of an invalid prediction with its teacher.

This is compatible conceptually with the separate JeV finite-choice surrogate
path, but these runs use native observations, not JeV scoring. They update the
graph edit encoder and readout—not reconstruction heads, a lossless codec, or an
NCA. Expected operation-bag cosine is not semantic equivalence or reconstruction
fidelity.

## Reproduction and generated reports

```bash
python -m jevops.rejection_training \
  --project-root /path/to/core-project \
  --environment-sha256 "$DEPENDENCY_MANIFEST_SHA256" \
  --epochs 80 --seed 17 --learning-rate 0.25 \
  --output-dir /path/to/new-native-rejection-run
pytest -q --test-seal=off tests/test_candidate_audit.py tests/test_rejection_reports.py
```

Use `--lake` for an appropriate Lake project. The native runner enables bounded
JSON compiler diagnostics. It writes `experiment.json` (full receipts, candidate
audits and checkpoints), `measurement.json`, and `summary.md` directly to files.
It refuses existing output directories and prints only a short status.

Report-only regeneration does not invoke Lean or train anything:

```bash
python -m jevops.rejection_training \
  --report-from /path/to/run/experiment.json --output-dir /path/to/new-reports
python -m jevops.rejection_reports /path/to/lr-005 /path/to/lr-015 /path/to/lr-025 \
  --output-dir /path/to/new-comparison
```

The comparison checks artifact hashes and matching data, grammar, native audit
decisions, toolchain, seed, epochs and update counts. It retains all supplied runs
and ranks using training acceptability/correctness followed by CE plus cosine,
not totals containing different penalty weights. This is training-only sequential
development, not a preregistered independent evaluation.

## Observed limitation, retained rather than hidden

Three native Lean 4.34.0 controls used learning rates 0.05, 0.15 and 0.25, seed 17,
80 epochs, eight training examples and 640 updates per arm. Each audit made 21
distinct native compilations: eight identities, ten admitted shorter candidates
and three recognized `rfl` rejections; no unknowns.

All graph variants selected acceptable proofs on 8/8 cases but the minimum-length
teacher on only 6/8, saving 72 source tokens. The fixed-feature policy selected all
eight teachers at learning rates 0.15 and 0.25, saving 74. The pure length selector
selected three rejected proofs and received only 44 verified saved tokens.

The auxiliary penalty reduced rejected probability mass but did not change the
chosen proofs and worsened CE versus its same-rate graph control. Accordingly,
all three graph training runs failed the full shortest-teacher gate. No checkpoint
was promoted. Avoiding an invalid short proof is useful; it is not evidence that
the learned encoder beats the stronger fixed-feature policy.

See the [generated comparison](tests/fixtures/rejection_training_control/summary.md)
and [historical measurements](tests/fixtures/rejection_training_control/measurement.json).
These are training observations, not fresh verification, an arena high score or
held-out generalization. The representation/update path needs further diagnosis;
simply increasing this penalty is not supported by these results.
