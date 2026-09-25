# Verified structural training pairs

The expression codec now has an opt-in bridge to the isolated rewrite
distillation runner. It recompiles original/shorter **training** endpoints,
retains their native DAGs, and supplies admitted shorter targets to the existing
sparse edit learner. This is not graph-autoencoder training, live JeV feedback,
NCA training, or automatic outer-router integration.

## Admission contract

`jevops.structural_training.collect_structural_pairs` takes a caller-owned split
manifest, candidate target text and a trusted compiler callback. It never uses
saved teacher receipts as proof authority. The production callback is
`router_tuning._lean_compiler(..., kernel_only=True, export_dags=True,
environment_sha256=...)`.

For each strict training improvement, admission requires:

- Exactly one named theorem, unchanged textual envelope, supported tactic bodies
  and an explicit statement without inference holes. The bounded prelude allows
  imports and universe declarations, not hidden helpers/axioms/options. Binder
  defaults and ambiguous header delimiters are rejected by this bounded adapter.
- Exact tactic-body round trip through the existing target IR. A verified text
  target must not silently become a different, unverified training label.
- Fresh successful source and target compilation, source/compiled-input hashes,
  the standard axiom audit, native DAG round trips and decoded-proof kernel checks.
- Matching dependency fingerprint, exporter hash and Lean toolchain; artifact
  and DAG digests are checked. The two artifact-bound graph environments normally
  differ, because the original and rewritten compiled modules differ.
- Identical structural declared-type fingerprints and ordered universe parameter
  lists. This deliberately rejects some definitionally equivalent types; it is
  not a semantic-equivalence oracle. Target axioms must be a subset of source
  axioms, even if new axioms would be in the standard allowlist.
- Strictly fewer proof-body tokens under `lra-local-ws-punct/v1`, with neither
  unique nor expanded proof-expression node counts increasing.

Costs are recounted from validated graphs, not copied from a candidate's size
claims. Each root's unique-node count excludes unrelated nodes in the combined
proof/type table. Numbering-independent fingerprints include binder names,
annotations, levels and supported metadata. They are structural fingerprints,
not proofs of equivalence; environment identity is checked separately.

Expression counts do not unfold constant bodies or include universe/name/string
payload substructure. Stored bytes, source tokens, expression nodes and kernel
cost remain different measurements. No globally minimal proof is claimed.

Rejected, missing, timed-out, over-budget and unsupported candidates create
rejection decisions, never teacher labels. Exact identity controls are recorded
separately, not called compression. The default limits are 32 training rows,
50,000 graph nodes per export and 64 MiB of retained graph JSON; hard limits are
64 training rows and 100,000 nodes per export. At most two compilation callbacks
are made per attempted nonidentity pair, with no retry loop.
These capture calls are additional to the runner's cached `--max-compiles`
budget and are reported separately; each also invokes the native exporter.

## Training and split boundary

Nontraining targets are not read or compiled by this collector. Pair and graph
tables contain training data only. Duplicate IDs and whitespace-normalized
duplicate source texts are rejected across the manifest. Caller ownership of
the split remains essential: this is not repository/theorem-family decontamination,
and renaming a theorem does not make it an independent mathematical holdout.

The isolated runner calls the structural gate before preparing its edit grammar
or updating weights. Any rejected nonidentity training target aborts the run
before training; at least one compressed pair is required. Accepted pair targets
feed ordinary supervised operation/edit CE and cosine objectives. Existing
identity controls retain their separate, compiler-audited source labels.

The graphs are retained for future structural models, but **graph features do
not drive the current update**. JeV remains a separate auxiliary gradient API;
it cannot make an invalid target enter this teacher set. No training objective
is replaced by a storage-size score.

A separate [source-DAG feature experiment](STRUCTURAL_FEATURES.md) now consumes
source graphs in a single-step sparse edit head. That experimental runner does
not change the endpoint bridge's default behavior or existing checkpoints.

This increment supports endpoint supervision only. Combining it with
`--trajectory-training` is rejected until every adjacent edge can be given the
same contract. Development/canary evaluation and post-freeze holdout evaluation
remain in the existing runner. Repeatedly observed canaries are development
evidence, not untouched final tests.

The training-pair guard does not certify future model predictions. Use
`--cost-guard` as well to require expression non-growth for independently rendered
evaluation predictions. Failures remain failures; no teacher replaces a raw
prediction. Nothing promotes a checkpoint or changes an official arena score.

## Usage

Supply a genuine caller-owned dependency manifest fingerprint. The exporter
binds it to actual compiled artifacts but does **not** independently verify the
full dependency closure. Hashes bind records; they do not authenticate arbitrary
receipts, callbacks or split assignments. Lean compilation is not a sandbox for
untrusted imported metaprograms.

```bash
python -m jevops.rewrite_distillation \
  --project-root /path/to/project --lake \
  --structural-pairs --environment-sha256 "$DEPENDENCY_MANIFEST_SHA256" \
  --cost-guard --freeze-reconstruction-heads --epochs 12 \
  --output /path/to/new-run.json

python -m jevops.refactor_report \
  --run /path/to/new-run.json --output-dir /path/to/new-report --archive-inputs
```

The existing report generator writes a compact structural-admission summary and
pair hashes. Full graphs/receipts stay in the raw run (and its optional compressed
archive), not an LLM-generated report. A run with a failed structural gate has
no trained checkpoint; inspect its raw rejection decisions rather than reporting
it as a completed training run.

Library callers can collect pairs directly and pass their `text`/`target_ir`
fields to `coerce_training_example`. That low-level training API still trusts
its caller: recompile persisted proposals when restoring provenance or changing
the environment; a serialized `teacher_admitted` Boolean is not proof authority.

## Tests

```bash
python -m pytest -q tests/test_structural_training.py tests/test_expr_dag.py
```

The [generated native smoke report](tests/fixtures/structural_pair_report/summary.md)
archives a 12-update frozen-reconstruction experiment: one training theorem and
one renamed same-family theorem in each evaluation split. Its compressed input
receipts, checkpoint and pair graphs are retained, and offline tests reproduce
their hashes and raw predictions. This tiny alias-removal check is not arena
evaluation or evidence of transfer to unseen theorem families.

Tests distinguish fake callback fixtures from real Lean experiments. They cover
stale/malformed bindings, type/toolchain changes, axiom growth, expression growth,
false size claims, target-IR corruption, resource limits and excluded splits.
Native tests recompile both endpoints, run sparse learning rounds and check raw
predictions. A bounded native distillation test generates its report using code;
an optional Mathlib test uses `JEVOPS_MATHLIB_PROJECT`. Fixture environment hashes
do not establish full dependency-closure authentication or arena generalization.
