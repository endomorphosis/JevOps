# Solver feedback and verified rewrite trajectories

Research and implementation: 2026-09-22. Builds on the 33-family catalog,
K-map/QM/BDD/e-graph reductions, finite and linear invariants, and
[frozen reconstruction edit adapter](CERTIFIED_REFACTORING.md). This increment
improves teacher discovery and supervision; it is not a complete Lean optimizer.

## Implemented pipeline

`solver_feedback.py` locates supported whole tactic lines and probes their
question-mark variants. The JSON compiler adapter binds information messages
to the exact source SHA, file, line and column. Only a bounded single-line
suggestion with an allowed tactic head is considered. Wrong locations, foreign
files, missing audits, truncated/malformed messages and unsafe syntax abstain.
The original theorem header never changes. Every shorter suggestion is compiled
again without the question mark and subjected to the strict transitive-axiom
audit. A successful query alone is not admission evidence.

The collector and isolated training runner explicitly use
`lra-local-ws-punct/v1` for body length, including punctuation and Unicode. A
regression test compares it directly with the frozen arena implementation.
This fixes an import-order hazard in the older autoencoder helper: importing
the arena could switch its implicit fallback counter. Earlier standalone
reports used the identifier-only fallback and must not be compared directly
with these counts. The router collector uses the same consumer counter as
the surrounding router search; it does not silently replace that contract.

The router's opt-in branch considers one verified source per round with at most
eight compiler requests, two sites and two rounds. It registers a replayed
candidate through the existing rule, winner and training path. Adapters without
structured diagnostics abstain; in particular the historical arena bridge does
not gain suggestion support simply by enabling the flag. No live LLM is needed
to use the collector. The standalone adapter requires named top-level theorems;
its strict audit permits `propext`, `Classical.choice`, `Quot.sound`, not native
axioms or `sorryAx`. It is not an independent kernel implementation.

`rewrite_trajectories.py` converts connected teacher traces into adjacent
source→shorter-source pairs. It rechecks every state rather than trusting a
persisted receipt, requires byte-identical theorem envelopes, and accepts at
most 16 strictly shortening edges. No-change controls have identity labels;
shortened endpoints do not acquire invented stop labels. Proof IDs and split
provenance stay attached to each edge. Only training edges mine templates or
update weights. Held-out paths are scored after the checkpoint freezes.

The opt-in distillation runner trains the existing sparse copy/edit selector on
these adjacent pairs. It separately reports teacher-path CE, expected
operation-cosine loss, total/labeled step counts and complete-example counts.
Missing labels remain unavailable, never zero loss. Regression gates reject
non-finite metrics, changed coverage and CE/cosine-loss increases. Endpoint
losses and compiler acceptance of the raw independent prediction remain
separate; a good teacher-path loss cannot replace an invalid output.

Inference still uses only the source and frozen parameters. It does not query
solvers, read teachers or repair failed outputs. `--freeze-reconstruction-heads`
keeps operation/latent weights fixed while learning edit selection. The
trajectory option currently belongs to the isolated distillation runner; the
router still trains its selected verified endpoint teachers. These are lexical
span rules, not typed Lean `Expr` transformations or a pretrained neural model.

## Kernel research: practical next directions

| Method | Research-grounded use here | Status / necessary boundary |
| --- | --- | --- |
| Solver-used premise sets | Replay `simp?`, `grind?`, `linarith?` output, then train on the checked edit | Implemented, bounded single-line subset; no speed guarantee |
| Guided equality saturation | Let an LLM propose intermediate equations/sketches to divide difficult search | Research direction; existing e-graph is binder-free Boolean only |
| Congruence explanation minimization | Prefer small equality certificates before proof reconstruction | Not implemented; certificate size is not source-token size |
| Incremental edit supervision | Train at intermediate states instead of only distant endpoints | Implemented for verified teacher paths, with coverage reporting |
| On-policy dataset aggregation | Collect mistakes at model-reached states and request new verified teacher steps | Future work; current paths are not DAgger |
| Exact linear certificates | Remove redundant premises and supervise a smaller `linarith only` proof | Implemented previously; incomplete bounded rational search |

Lean documents `grind?` as a way to obtain used-theorem restrictions or replay
scripts. Our collector currently skips multiline scripts and never assumes a
suggested set is globally minimal. `simp?` and related tactics provide a similar
route to explicit simplifier arguments. Installed-version compilation decides
availability, including unsupported question-mark variants.
[Lean grind minimization](https://lean-lang.org/doc/reference/latest/The--grind--tactic/Minimizing--grind--calls/),
[Lean tactic reference](https://lean-lang.org/doc/reference/latest/Tactic-Proofs/Tactic-Reference/).

Mathlib's `linarith?` greedily removes hypotheses from its suggestion by default.
Its coefficient oracle is untrusted; Lean reconstructs proof terms. This makes
oracle-produced support a useful teacher proposal without giving numerical
search proof authority. General nonlinear minimization and integer completeness
do not follow from this mechanism.
[Mathlib frontend and reconstruction description](https://leanprover-community.github.io/mathlib4_docs/Mathlib/Tactic/Linarith/Frontend.html).

Guided equality saturation splits a difficult rewrite search using intermediate
terms or sketches. Its Lean case study reconstructs equality witnesses and lets
Lean check them. My implementation inference is to have the LLM propose guides,
not axioms or assumed lemmas. General support here still needs typed/scoped
expression serialization, binder-safe matching and Lean-side reconstruction;
the current Python Boolean e-graph is insufficient.
[Guided Equality Saturation, POPL 2024, §§3–4](https://thok.eu/publications/2024/popl.pdf).

Small Proofs from Congruence Closure distinguishes difficult global proof-size
optimization from a relaxed tree metric and practical greedy minimization.
That motivates measuring and optimizing proof explanations separately from
tactic spelling. It does not establish that this repository's token search is
optimal or has the paper's performance.
[Small Proofs from Congruence Closure](https://arxiv.org/abs/2209.03398).

Incremental tree-edit learning motivates exposing intermediate edit decisions,
but our sparse lexical policy is not that paper's neural tree architecture.
DAgger motivates gathering supervision at learner-visited states to address
sequential distribution shift. Offline teacher-path training does not implement
that guarantee; it is a smaller, auditable step.
[Learning Structural Edits](https://arxiv.org/abs/2101.12087),
[DAgger](https://arxiv.org/abs/1011.0686).

The local `ipfs_datasets_py` report
`docs/implementation/reports/HAMMER_LEANSTRAL_LEGAL_IR_OPTIMIZATION_REPORT.md`
requires durable lineage, quality gates and matched resource measurements for
promotion. We retain old failed checkpoints and separate new receipts. These
small experiments do not satisfy its staged production contract.

## Measured results

The pinned-token run used ten training proofs, twelve adjacent examples, nine
templates and 40 epochs (480 updates). It made 134 unique compiler calls,
including 20 rejected drafts. The original and every admitted teacher state
passed audit. No held-out path supplied grammar entries or weight updates.

| Evaluation | Valid | Shortened | Pinned body tokens before → after |
| --- | --- | --- | --- |
| Ten canaries | 10/10 | 9/10 | 71 → 34 |
| Final synthetic holdout | 14/14 | 12/14 | 111 → 63 |
| Same holdout, zero edit weights | 14/14 | 0/14 | 111 → 111 |
| Solver-feedback holdout, included above | 1/1 | 1/1 | 15 → 7 |
| Two-branch application, included above | 1/1 | 1/1 | 17 → 15 |
| Two-branch eta, included above | 1/1 | 1/1 | 20 → 12 |

Canary teacher-path CE fell **0.760725 → 0.116857** and expected operation-cosine
loss fell **0.308967 → 0.059473**, with all 12 steps labeled. On the final
holdout, path CE was **0.818173 → 0.286782** relative to zero edit weights,
and expected cosine loss was **0.255657 → 0.047115**, with **18/18 steps** labeled
across all 14 proofs. One-step endpoint-label coverage remains **10/14** and is
reported separately. It has not been disguised as complete endpoint coverage.

Canary output cosine rose **0.2654 → 0.45**. Operation CE remained **4.343805**,
because the reconstruction parameters are frozen, not because the base encoder
learned better reconstruction. These are structural diagnostics; only Lean
certifies the emitted proofs. Composed-path CE remains higher than the simple
families, leaving clear room for better multi-edit training.

The known arena original again shortened **482 → 481**; its historical seed
shortened **392 → 391**. Both passed strict Lean 4.26.0 audit and the CE/cosine
gates. This **matches**, not beats, the existing 391-token local best. Those
inputs are known regression data, not unseen arena canaries. Most synthetic
splits also share alpha-renamed structural families; no semantic-family
decontamination, full-arena result, speedup or production promotion is claimed.
There was no live LLM call, NCA training or Typesafe-authorized admission in
these experiments. Those existing components were not expanded in this change.

The first run used the legacy identifier-only counter; the pinned-token rerun
produced the identical checkpoint and raw predictions. Thus the real arena
evaluation applies to that exact same frozen state, independently of the
synthetic counter correction. Earlier receipts and failed CE gates are retained.

Artifacts:

- [Checkpoint](tests/fixtures/trajectory_edit_checkpoint.json), state SHA
  `d70bac84d9a58f09d29909d15a125b340221a1f8145c267f7480b79b170baf7b`.
- [Evidence](tests/fixtures/trajectory_edit_evidence.json): audited teacher
  traces, raw holdout predictions, coverage/metric gates, ablations, a complete
  position-bound solver-feedback example, arena results and raw receipt hashes.

Real solver tests cover `simp?`, Mathlib `linarith?`, and a `grind?` hint that
does not improve length. Negative tests reject forged/disconnected paths,
changed statements, failed intermediate proofs, unverified suggestion replay,
invalid budgets, non-finite losses and lost coverage. Saved-checkpoint tests
independently reproduce predictions and teacher-path losses; those tests use
mock compilers and do not replace the separately recorded real Lean runs.

Final validation: **343 tests passed** with the cached Mathlib project enabled
(236.46 seconds), plus `git diff --check` and Python compilation checks. The one
warning is the existing optional `ipfs_datasets_py` deprecated import. The
cached Strata checkout is clean after the arena run. Core solver experiments
used Lean 4.34.0; the arena retained its pinned Lean 4.26.0 environment.

## Reproduce

```bash
python -m jevops.rewrite_distillation --extended --compositional-holdout \
  --trajectory-training --solver-feedback --freeze-reconstruction-heads \
  --epochs 40 --max-compiles 256 --output /tmp/new-trajectory-run.json
python papers/completion/lean_refactor_arena/harness/evaluate_rewrite_checkpoint.py \
  --checkpoint /tmp/new-trajectory-run.json \
  --name CallElimCorrect.substOldPostSubset \
  --reference-fixture tests/fixtures/kernel_refactor_local_best.json \
  --output /tmp/new-trajectory-arena.json
python -m pytest -q tests/test_solver_feedback.py tests/test_rewrite_trajectories.py
```

Choose unused output paths. Mathlib tests require `JEVOPS_MATHLIB_PROJECT` to
point to an already built project. Never run arena source-splicing evaluations
concurrently. No production checkpoint is promoted by these commands.
