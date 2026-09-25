# Proof-cost-aware compression: implementation and research

Research checked 2026-09-22. This extends the existing
[method catalog](KERNEL_REFACTORING_RESEARCH.md), not a claim that every Lean
refactoring method or globally shortest proof has been implemented.
Experimental measurements are produced by `jevops.refactor_report`, not
hand-assembled evidence files.

The [generated run summary](tests/fixtures/guarded_rewrite_report/summary.md)
and adjacent checkpoint/evidence include compressed raw input receipts for
reproduction. This specialized checkpoint does not reproduce the older arena
shortening; it is not a replacement for the previous best. Joint mixed-family
training with guarded baseline regression is still needed before promotion.

The [structural autoencoder and JeV surrogate learning plan](STRUCTURAL_AUTOENCODER_PLAN.md)
extends this baseline with an explicit gradient path from fuzzy scores on lossy
proposals, alongside the separate [lossless expression codec](EXPR_DAG_CODEC.md). It preserves
CE/cosine objectives and Lean admission. A separate opt-in finite-edit JeV
gradient API is now implemented; it was not used by the experiments below and
does not yet run automatically in the outer router.

## What is implemented

| Family | Implementation | Boundary |
| --- | --- | --- |
| Boolean identities, K-maps/QM, BDDs, equality saturation | Existing `logic_ir`, `equality_saturation`, reduction catalog | Bounded propositional models, not dependent Lean expressions |
| Structural tactics, slicing, solver support minimization | Existing reduction catalog and position-bound solver feedback | Every proposal requires compilation in the original environment |
| Elaborated term recovery | `typed_terms` replays bounded `show_term` output | Single-line terms; no arbitrary binder rewriting |
| Constructive proof terms | New `constructive_proofs` | Explicit named propositional binders, eight atoms, bounded incomplete search |
| Finite invariants and parity | Existing Houdini/reachability/GF(2) analysis | Explicit finite Boolean transition model |
| Affine inequalities | Existing exact rational Farkas certificates | Bounded, incomplete certificate search for explicit integer systems |
| Difference-bound redundancy | New `difference_bounds` | Explicit integer constraints `x_i - x_j ≤ c`, at most 16 variables / 64 constraints |
| Teacher and student size admission | New opt-in `--cost-guard` | Both unique structural nodes and expanded expression-tree nodes must not grow |

Constructive search performs conjunction/iff elimination, implication chaining,
contradiction, introductions, disjunction injection and case analysis. It records
supporting hypotheses and emits ordinary Lean terms, not a trusted Boolean
equivalence claim. Unsupported dependent types, arbitrary imports/declarations,
ambiguous binders, and resource exhaustion abstain. Classical excluded middle is
not silently assumed. Search retains small local explanations but is neither a
complete intuitionistic decision procedure nor a globally optimal extractor.

Difference-bound closure uses exact integer shortest paths. Redundancy removal
is sequential, so duplicate constraints cannot all disappear at once. Final
path certificates refer only to retained constraints; an independent path
checker verifies connectivity and telescoping bounds. Negative cycles report
inconsistency rather than a non-vacuous reduction. Standalone Lean obligations
use only certified supporting hypotheses and are checked with `omega`. This
does not parse arbitrary programs or automatically infer loop invariants; full
invariant inference still requires explicit initiation/preservation obligations.

## Training and admission

`--cost-guard` is integrated into the isolated distillation runner, including
deterministic candidates, solver suggestions, elaborated terms and constructive
terms. A valid-but-larger candidate is rejected as a teacher without relabeling
it as a false theorem. Missing, saturated or unbound measurements cannot pass.
Rejected checks retain source digests. Raw frozen predictions are checked again;
an invalid or larger prediction is reported, never replaced with a teacher.

Source text, theorem envelope, proof validity, expression size, operation CE,
edit CE, output cosine, expected edit-cosine loss and label coverage remain
separate. Short source text is not a proof-size or checking-speed measurement.
The inspector reads the exact compiled theorem artifact, counts structural
sharing and expanded expression nodes, and audits axioms. It does not unfold
referenced constants, count universe-level subtrees or literal payload bytes,
measure physical-memory sharing, time the kernel alone, or run an independent
kernel implementation. Import/dependency closure reproducibility remains a
separate requirement.

The new curriculum trains the existing sparse lexical copy/edit selector on
Lean-verified shorter proofs; it is not a new neural typed-tree autoencoder.
Only training examples mine templates and update weights. Reconstruction heads
can be frozen to preserve operation CE. Development and holdout families are
mostly alpha-renamed structural relatives, explicitly not semantically disjoint.
Difference-certificate examples pass through this same compiler/cost-guarded
teacher path, rather than receiving an assumed reward from the Python oracle.

The router has an independent `--constructive-terms` proposal branch. The new
cost guard is currently a **distillation-runner** admission policy; enabling
constructive proposals in the router does not automatically guard every router
winner by expression size. No production checkpoint is promoted here.

## Research conclusions and next kernel methods

1. **Exploit definitional equality before adding equality proofs.** Lean's
   conversion rules include computational reductions and proof irrelevance.
   Prefer replayable `rfl`, definitional simplification, projections and existing
   terms where they suffice. Proof irrelevance does not mean that any fabricated
   term proves a proposition, or that all definitions can be erased. The current
   implementation uses the compiler for this authority; binder-safe general
   `Expr` normalization remains future work.
   [Lean type system](https://lean-lang.org/doc/reference/latest/The-Type-System/),
   [simplifier rewrite rules](https://lean-lang.org/doc/reference/latest/The-Simplifier/Rewrite-Rules/).

2. **Minimize explanations, not just tactic names.** Congruence-closure proof
   minimization has difficult global objectives; the cited work studies a
   relaxed proof-tree metric and practical greedy extraction. Our engineering
   inference is to maintain source/term-size frontiers and minimize explanation
   paths before reconstruction. Our structural-node guard is implemented; that
   paper's extraction algorithms are not.
   [Small Proofs from Congruence Closure](https://arxiv.org/abs/2209.03398).

3. **Treat dependent equality saturation as a separate architecture.** Bound
   variables, substitution, shifting, definitional equality and explanation
   reconstruction cannot be handled by extending a bare-atom Boolean e-graph.
   An eventual typed engine needs scoped variables, environments and type-checked
   witnesses for every extracted rewrite. As of this research check, the
   `lean-egg` maintainers mark their tactic deprecated and recommend `grind`.
   Accordingly, the nearer-term integration target is bounded `grind?` replay,
   not installing an unpinned obsolete backend.
   [Binding/equality-saturation research](https://arxiv.org/abs/2405.10188),
   [lean-egg maintenance status](https://github.com/marcusrossel/lean-egg),
   [Lean grind minimization](https://lean-lang.org/doc/reference/latest/The--grind--tactic/Minimizing--grind--calls/).

4. **Use specialized invariant domains with checkable explanations.** Difference
   bounds provide a useful exact restricted domain; octagons, congruences and
   polyhedra cover other relationships. This change implements difference-bound
   redundancy and witness generation, not widening, octagonal closure or a
   general abstract interpreter. The Farkas path remains complementary: Mathlib
   reconstructs proofs from untrusted arithmetic search rather than accepting
   numerical optimizer output as logical truth.
   [Miné's difference-bound domain](https://arxiv.org/abs/cs/0703073),
   [Mathlib linarith reconstruction](https://leanprover-community.github.io/mathlib4_docs/Mathlib/Tactic/Linarith/Frontend.html).

5. **Separate proof authority from retrieval and neural feedback.** Cosine,
   graph kernels, Typesafe scores, LLM proposals and cellular-automaton feedback
   may rank proposals, but cannot override a failed Lean check. Independent
   checking is a worthwhile additional deployment boundary, not a capability
   supplied by this inspector. No independent checker, new Typesafe/NCA training,
   live LLM tuning, full-arena win or trillion-token throughput is claimed.
   [Lean4Lean](https://arxiv.org/abs/2403.14064).

The local `ipfs_datasets_py` production contract also requires fixed lineage,
matched cold/warm measurements, hard quality gates and staged rollout evidence:
`docs/implementation/reports/HAMMER_LEANSTRAL_LEGAL_IR_OPTIMIZATION_REPORT.md`.
These small experiments do not satisfy that production promotion contract.

## Reproduce without generating reports through the LLM

Use fresh output filenames/directories; existing receipts are never overwritten.

```bash
python -m jevops.rewrite_distillation --constructive-curriculum \
  --difference-curriculum --constructive-terms --cost-guard \
  --trajectory-training --freeze-reconstruction-heads --epochs 40 \
  --seed 20260927 --max-compiles 192 --output /path/to/run.json
python -m jevops.measure_checkpoint --checkpoint /path/to/run.json \
  --family-prefix '' --max-examples 32 --require-expression-nonregression \
  --output /path/to/expressions.json
python -m jevops.refactor_report --run /path/to/run.json \
  --expressions /path/to/expressions.json --archive-inputs --output-dir /path/to/new-report
```

The generated summary exposes failures and coverage; JSON carries full measured
evidence, checkpoint state and provenance. Reporting success is not gate success.
