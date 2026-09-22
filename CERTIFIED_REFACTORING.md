# Certified reductions and learning without reconstruction drift

Research and measurements: 2026-09-22. This extends
[rewrite distillation](REWRITE_DISTILLATION.md) to **33 catalog families**, plus
programmatic invariant analyzers. It does not implement every Lean transformation,
prove a global minimum or establish arena leadership.

## New coverage

| Method | Implementation | Boundary |
| --- | --- | --- |
| Application fusion | `apply f; exact h` → `exact f h` on separate, equally indented lines | Unary identifiers; Lean checks implicit arguments and goals |
| Eta reduction | `intro h; exact f h` → `exact f` | No arbitrary substitution or dependent binder manipulation |
| Solver-argument reduction | Whole-list, chunk and individual deletions from explicit `simp`, `rw`, `grind`, `linarith`, etc. lists | Balanced delimiters; every candidate needs compilation |
| Linear constraint redundancy | Exact nonnegative rational combination certificates | Non-strict integer linear constraints; no floating-point decisions |
| Guarded affine invariants | Pull back candidates through an explicit affine update; check initiation and preservation to a fixed point | Unbounded integer model, not automatic source-program analysis |

The three catalog methods enter the existing rotating sweep, router and
teacher-collection paths. Existing K-map/QM, Boolean algebra, ROBDDs,
propositional e-graphs, finite Houdini/GF(2), arithmetic tactics and proof slicing
remain available. See [the broader method survey](KERNEL_REFACTORING_RESEARCH.md).

`tactic_arguments.py` distinguishes commas inside `(a, b)`, `⟨a, b⟩` and nested
lists from outer lemma separators, preserving suffixes such as `at h` and
`using h`. Malformed delimiters, comments, strings, quotations, semicolons
inside arguments and oversized lists abstain. This restricted scanner is not
a Lean parser. List deletion is a proposal, never an unconditional rewrite.

## Linear certificates and invariant semantics

`linear_invariants.py` represents constraints `a · x ≤ b` with up to four integer
variables. It searches for rational `w_i ≥ 0` and slack `s ≥ 0` satisfying:

```text
sum_i w_i * premise_i.coefficients = target.coefficients
sum_i w_i * premise_i.bound + s    = target.bound
```

Small support sets are enumerated and solved by exact rational elimination.
A separate checker verifies identities, dimensions, signs and arithmetic bounds.
Limits include 16 premises, 512 support attempts by default (4,096 maximum),
and input integers of at most 32 bits. No external LP solver is installed.

Failure means `unknown_no_certificate` or `unknown_budget`, **not false**.
For example, integer `2*x ≤ 1` entails `x ≤ 0`, but its rational relaxation does
not. Integer rounding, strict inequalities, disequalities, disjunctive joins,
widening, nonlinear dynamics and nonlinear certificates are outside this module.

For a guarded transition `x' = A*x + c`, initial constraints must imply each
candidate; the active candidate conjunction plus guard must imply its affine
pullback. Unproved candidates are removed and the others rechecked, since
removing support can invalidate them. Up to eight candidates/eight guards are
supported. This gives a conservative certified subset, not the greatest
inductive set. Sequential redundancy deletion retains each certificate's exact
premise indices, avoiding simultaneous removal of mutually supporting facts.

Generated obligations restrict `linarith only` to nonzero certificate support.
Lean reconstructs its own proof, not trusting Python's numerical certificate.
Preservation goals render the **original affine update**, so Lean also checks
the algebra of the pullback. Analysis reports retain `lean_verified: false`;
successful compilation is a separate receipt. Binding an arbitrary source
program to this explicit transition model remains the caller's responsibility.

Measured example: from `x=y=0`, updating both by one retains `x≤y`, `y≤x` and
`0≤x`, while discarding the unproved bound `x≤5`. Six generated
initiation/preservation obligations and one redundancy obligation passed strict
Mathlib axiom audit. Dependencies were `Classical.choice`, `Quot.sound`,
`propext`; no native or `sorryAx` dependency was accepted. Tests also require
Lean to reject a false stronger bound.
[Saved linear evidence](tests/fixtures/linear_invariant_evidence.json).

## Kernel research and remaining work

Mathlib separates `linarith`'s untrusted coefficient oracle from proof-term
reconstruction. This supports proposing smaller premise sets while leaving
Lean authoritative. Rational completeness does not imply integer completeness;
our bounded Python search is narrower still.
[Reconstruction](https://leanprover-community.github.io/mathlib4_docs/Mathlib/Tactic/Linarith/Verification.html),
[frontend](https://leanprover-community.github.io/mathlib4_docs/Mathlib/Tactic/Linarith/Frontend.html).

Houdini's candidate-removal fixed point motivates rechecking dependent
invariants. With our incomplete certificate search, removal means unproved,
not necessarily false.
[ExplainHoudini](https://www.microsoft.com/en-us/research/publication/explainhoudini-making-houdini-inference-transparent/).

`simp?` and `grind?` expose sufficient lemma sets. We now minimize existing
explicit lists; compiler-suggestion harvesting remains future work. Shorter
syntax or fewer lemmas alone does not prove faster kernel checking.
[Lean tactic reference](https://lean-lang.org/doc/reference/latest/Tactic-Proofs/Tactic-Reference/),
[minimizing grind calls](https://lean-lang.org/doc/reference/latest/The--grind--tactic/Minimizing--grind--calls/).

For statistical kernels, WL features remain a candidate for ranking similar
proof-dependency neighborhoods, not correctness. Sparse explicit features avoid
a corpus-wide dense Gram matrix. WL/RBF accuracy and throughput have not been
measured in this repository.
[Weisfeiler–Lehman graph kernels](https://jmlr.org/papers/v12/shervashidze11a.html).

Still unimplemented: general typed Lean-expression rewriting, binder-aware
equality saturation, proof-DAG minimization, solver suggestion harvesting,
nonlinear invariant synthesis and source-to-transition extraction. The Lean
kernel is unchanged. Goal consequences are never inserted as assumptions.

## Learning without reconstruction drift

`AutoencoderConfig(freeze_reconstruction_heads=True, train_rewrite_policy=True)`
freezes operation biases/transitions/features and latent biases/features while
training rewrite selection with edit CE and expected operation-cosine loss.
The router exposes the same option; default joint training is unchanged.
Freezing without rewrite training fails configuration validation.

This is parameter isolation, not LoRA or a Transformer. Freezing a base while
adapting a small component is the relevant analogy; LoRA's architecture and
efficiency results do not transfer here. These reconstruction heads are frozen
at initialization, **not** at a strong pretrained checkpoint.
[LoRA](https://arxiv.org/abs/2106.09685).

The earlier tiny joint-training run worsened arena operation CE. The new mode
preserves that CE by construction while the edit head learns. It does not show
improved reconstruction modeling or solved generalization. The failed checkpoint
and its regression test remain separate and unchanged.

The extended curriculum has nine training rows/eight templates, 40 epochs and
360 updates, adding application, eta and solver-list teachers. All sources and
teachers are strictly audited before training. Four additional holdouts test
branch compositions, a new integer-equality context and an unchanged `rfl`
control. They never grow the grammar or update weights. Runs with/without the
extra holdouts produced the identical checkpoint digest.

Inference sees only source and parameters, with no teacher repair or compiler
search. Zeroing edit weights retains the grammar but removes all shortening.
The model can compose edits and sometimes shorten beyond a single-step teacher.

A separate real-Mathlib test connects linear certificates to training: generate
a smaller `linarith only` support, compile both proofs in the same envelope,
train the selector, then compile its shorter output with renamed hypotheses.
Edit CE improves and operation CE stays fixed. This is a small transfer test,
not learned general invariant synthesis.

## Measured results

| Evaluation | Valid | Shortened | Body tokens before → after |
| --- | --- | --- | --- |
| Nine canaries | 9/9 | 8/9 | 43 → 20 |
| Combined final holdout | 13/13 | 11/13 | 75 → 41 |
| Two-branch application, included above | 1/1 | 1/1 | 13 → 11 |
| Two-branch eta, included above | 1/1 | 1/1 | 16 → 8 |
| Same final holdout, zero edit weights | 13/13 | 0/13 | 75 → 75 |

Canary edit CE: **0.783251 → 0.131073**. Reported cosine:
**0.239333 → 0.444444**. Operation CE: **4.343805 → 4.343805**, because its
parameters are frozen. These are separate diagnostics, not semantic scores.
Combined holdout edit-label coverage is **11/13**: two multi-edit targets lack
single-step labels; missing edit loss is unavailable, not zero. The combined
run made 110 unique compile calls, including rejected teacher proposals.

Most splits share alpha-renamed structural families. Additional layouts/domains
are a stronger test, but not semantic-family decontamination.

| Known arena input | Tokens before → after | Operation CE | Metric gate |
| --- | --- | --- | --- |
| Frozen original | 482 → 481 | Unchanged, 4.343805 | Pass |
| Historical seed | 392 → 391 | Unchanged, 4.343805 | Pass |

Both passed strict Lean 4.26.0 audit in Strata commit
`451e5f047bafa010d178856db76c00029bfa4d7f`, with only `Quot.sound` and `propext`.
No arena data was trained on, but these known regression inputs motivated the
freeze experiment; they are **not unseen arena canaries**. This still only
matches the 391-token local best. No new high score, official score or production
promotion is claimed. Arena edit-label CE remains unavailable against the fixed
reference for the reasons documented in the earlier report.

Artifacts:

- [Checkpoint](tests/fixtures/certified_edit_checkpoint.json), state SHA
  `89017b8108011b0fddd8da7358d8d53ca22865a26e0d3639258c23b517307fdf`.
- [Learning/arena evidence](tests/fixtures/certified_edit_evidence.json), including
  holdout predictions, ablations, metrics and axiom audits.
- [Linear invariant evidence](tests/fixtures/linear_invariant_evidence.json).

The local `ipfs_datasets_py` guidance at
`docs/implementation/reports/HAMMER_LEANSTRAL_LEGAL_IR_OPTIMIZATION_REPORT.md`
was reviewed again. Its durable-lineage and separate semantic/resource gates
support preserving both old failure and new result. These experiments do not
meet its staged production/throughput contract. No NCA training, live LLM call,
paid service or production-memory update occurred here.

## Reproduce

```bash
python -m jevops.rewrite_distillation --extended --compositional-holdout \
  --freeze-reconstruction-heads --epochs 40 \
  --output /tmp/jevops-certified-edits-new.json
python papers/completion/lean_refactor_arena/harness/evaluate_rewrite_checkpoint.py \
  --checkpoint tests/fixtures/certified_edit_checkpoint.json \
  --name CallElimCorrect.substOldPostSubset \
  --reference-fixture tests/fixtures/kernel_refactor_local_best.json \
  --output /tmp/jevops-certified-arena-new.json
python -m pytest -q tests/test_linear_invariants.py tests/test_tactic_arguments.py \
  tests/test_rewrite_policy.py tests/test_rewrite_checkpoint.py
```

Use unused receipt paths. Real linear proof tests need `JEVOPS_MATHLIB_PROJECT`
pointing to a built project, otherwise they skip. Arena runs require the pinned
cache; never splice its source concurrently. The 15-row dataset digest is unchanged.

Final validation: **311 tests passed** with the real Mathlib project enabled
(192.27 seconds), plus `git diff --check`. The one warning is the existing
optional `ipfs_datasets_py` deprecated import. The cached Strata checkout is
clean after evaluation. Tests retain the old failed CE gate and independently
reproduce the new checkpoint's holdout outputs and passing arena metrics.

Next priorities: a broader training-only corpus, typed source-bound dependencies,
multi-step edit labels, and matched speed/memory measurements. Source-token
savings do not establish smaller proof terms or trillion-token throughput.
