# Lean proof minimization: research, implementation and trust boundaries

Research reviewed 2026-09-22. This extends [the existing reductions](LOGIC_REDUCTIONS.md),
not a claim that every Lean optimization is implemented. Arbitrary Lean proofs
cannot be covered by a complete finite tactic list or a universally terminating
global shortest-proof search. The practical target is the shortest **admitted
candidate found within a recorded budget**, for a fixed statement and environment.

## 1. Optimize the right artifact

Keep three objectives separate:

| Objective | What to measure | Common misleading shortcut |
| --- | --- | --- |
| Source proof length | Frozen benchmark tokenizer over the complete proof body | Counting only a tactic name, ignoring new helper declarations |
| Elaborated proof size | Lean `Expr` tree/DAG nodes and referenced declarations | Assuming a one-token `grind` has a small proof term |
| Verification cost | Elaboration/checking time, heartbeats, peak memory; cold/warm separately | Treating compilation startup or a cache hit as proof-checking speed |

Lean Refactor treats length, compilation cost and version compatibility as
distinct objectives. It uses version-aware strategy retrieval and compiler
feedback; its published results are not results for this repository. Our
design implication is to retain a verified Pareto frontier and measure costs
under the benchmark's pinned environment, rather than collapse all objectives
into token count. [Lean Refactor, 2026](https://arxiv.org/html/2605.20244v1).

Currently this repository measures source-body length and compile receipts.
The new slicing experiment records wall time per invocation. It does **not**
yet measure elaborated `Expr` DAG size or isolated kernel time. The e-graph's
`render_chars`/`ast_nodes` objectives concern propositional formulas, not arena
proof tokens. Only recompiling and measuring the complete proposed proof can
establish a proof-length improvement.

## 2. Kernel methods worth using

### Definitional reduction and proof irrelevance

Lean already checks beta, delta, iota and zeta reductions, with eta and
proof-irrelevance behavior. Use `rfl`, controlled `dsimp`, and appropriate
decidability procedures before expensive automation. Proof irrelevance applies
to proofs of the **same proposition**; it does not permit replacing a proposition
with a different one, equating arbitrary data, or discarding obligations.
Do not implement dependent binder substitution with string replacement.
[Lean's type system](https://lean-lang.org/doc/reference/latest/The-Type-System/),
[propositions](https://lean-lang.org/doc/reference/latest/The-Type-System/Propositions/).

Implemented: `kernel_reduce` proposes `rfl`, `dsimp; rfl`, `decide`,
`decide +kernel` and `decide_cbv`. Availability is version-specific and the
pinned compiler decides. No kernel modification is required. General proof-term
normalization, sharing and unexpansion are not implemented by this Python layer.

### Congruence closure, equality saturation and cost extraction

An e-graph retains equivalent alternatives instead of committing to the first
rewrite. Congruence rebuilding discovers equal parent terms after child classes
merge. Cost extraction can then select a shorter representative, including
transformations that temporarily expand terms before factoring them.
[egg, POPL 2021](https://arxiv.org/abs/2004.03082).

Implemented in `jevops.equality_saturation`: hash-consed enodes, union/find,
congruence rebuilding, 29 bounded classical Boolean rewrite rules, extraction
with acyclic size/depth limits, and final algebraic cleanup. Distribution,
factoring, absorption, complement, De Morgan, implication, iff and xor rules
have truth-table regression tests. Node/matching/iteration limits are explicit;
`saturated=False` and `global_minimum=False` are meaningful outcomes.
`egraph_minimize` routes the result into a Lean equivalence obligation and a
compiler-gated proof candidate. Python equivalence is not admission evidence.

For arbitrary Lean expressions, the hard parts are binders, universes, dependent
types and scope-preserving substitution. The Lean-expression e-graph research
describes capture, invalid matches and aliasing hazards. Slotted e-graphs make
binding structure explicit. Those are the appropriate designs for a future
typed Lean `Expr` implementation, not permission to extend the current bare-atom
Boolean IR by guessing syntax.
[Lean expressions in e-graphs](https://arxiv.org/html/2405.10188v1),
[Slotted E-Graphs, PLDI 2025](https://goens.org/publications/schneider_pldi25/).

The original `lean-egg` repository now marks the tactic deprecated and recommends
`grind`. Consequently this implementation adds no unpinned Rust/FFI dependency.
It uses native Lean `grind` proposals for general congruence reasoning and a small,
bounded Python e-graph only for propositional search hints.
[Maintainer notice](https://github.com/marcusrossel/lean-egg),
[Lean congruence closure](https://lean-lang.org/doc/reference/latest/The--grind--tactic/Congruence-Closure/).

### Controlled automation and proof reconstruction

Restricting `grind`'s theorem set can reduce search work. `grind?` can report the
lemmas actually used, which can be frozen as `grind only [...]`; that is distinct
from declaring the shortest tactic spelling the fastest proof.
[Minimizing grind calls](https://lean-lang.org/doc/reference/latest/The--grind--tactic/Minimizing--grind--calls/).

Implemented: `grind_control`, explicit simplifier-set proposals, existing simp
lemma deletion, and `rewrite_transport` proposals such as replacing
`simp [...] at h; exact h` with `simpa [...] using h`. Automatic harvesting and
replaying of `grind?`/`simp?`/`exact?` suggestion diagnostics is still future work.
Every optional Mathlib tactic is an invocation of the installed solver, not a
new implementation of that solver.

### Reflection, native evaluation, SAT and trust

`native_decide` uses native evaluation and adds an axiom dependency. Older Lean
versions can report `Lean.ofReduceBool`; newer versions use per-computation
axioms. A clean process exit therefore does not establish kernel-only checking.
[Lean axioms](https://lean-lang.org/doc/reference/latest/Axioms/).

`bv_decide` obtains a SAT certificate and validates it with a verified checker,
but that checker is run natively. The SAT solver is outside the trusted base;
the native compiler/checker execution remains part of it. This distinction is
now explicit in the tactic catalog. Do not describe this lane as axiom-free or
equivalent to `decide +kernel`.
[Bitvector automation](https://lean-lang.org/doc/reference/latest/Basic-Types/Bitvectors/).

Implemented: `jevops.proof_trust` audits the target's transitive axiom report,
including JSON Lean diagnostics. The strict allowlist is `propext`,
`Classical.choice`, `Quot.sound`. Missing/conflicting reports, `sorryAx`, native
axioms and other axioms fail closed. A caller can explicitly provide a different
fixed allowlist to the audit API; it must not be learned from candidate output.
This uses Lean's own checker and reports that no independent verifier was used.

`--kernel-only` is available in both the router CLI and the arena validation
harness. The standalone helper handles named top-level declarations and rejects
ambiguous namespace/section layouts. The arena adapter instead knows the exact
qualified benchmark declaration, appends its audit command to the spliced module,
checks each selected pinned version and restores source bytes in `finally`.
Without that flag, the arena's existing theorem-span admission policy remains
unchanged. Its module may contain unrelated `sorry` warnings; those alone neither
prove nor disprove a target's transitive dependency safety.

## 3. Invariant inference and reduction

Houdini starts with candidate annotations and removes ones that fail checking.
Removing an assumption can invalidate another candidate, so checks must repeat
to a fixed point. Failure explanations are valuable feedback for refining the
candidate set. [ExplainHoudini](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/paper-70.pdf).

Implemented in `jevops.invariant_inference`:

- Explicit Boolean initial states, transition relation and injective
  current/next-state mapping; at most four state bits and 32 candidates.
- Initiation and simultaneous-conjunction preservation checks, with removal
  rounds and concrete counterexamples. Mutually supporting invariants survive.
- Sequential redundancy elimination that preserves the inferred conjunction;
  duplicate invariants are not all deleted at once.
- Exact bounded reachable-state closure, kept distinct from inductiveness.
- Separate Lean initiation/preservation obligations, explicit vacuity flags,
  and `lean_verified=False` until an external compiler proves those obligations.

This complements existing K-maps, Quine–McCluskey, BDD support reduction and
entailed-literal/equality analysis. It is not general program invariant inference.
No transition relation is silently inferred from a Lean theorem statement, and
no goal consequence is inserted into the proof as an assumption. Infinite-state
abstract interpretation, polynomial ideals and CEGAR/IC3 require separate
representations and certificate reconstruction. A subsequent
[certified-refactoring implementation](CERTIFIED_REFACTORING.md) adds a bounded
exact Farkas search and guarded affine integer invariants with Lean obligations;
it is not a complete polyhedral or general program-analysis engine.

```python
from jevops.logic_ir import parse_formula as P
from jevops.invariant_inference import infer_invariants

report = infer_invariants(
    P("x ∧ y"), P("(xn ↔ y) ∧ (yn ↔ x)"),
    [P("x"), P("y"), P("True")], {"x": "xn", "y": "yn"},
)
assert report["kept_indices"] == [0, 1]
assert report["redundant_indices"] == [2]
# Compile report["initiation_obligation"] and report["preservation_obligation"].
```

## 4. Refactoring coverage

There are now 33 catalog families, including terminal alias, symmetry,
application/eta and balanced solver-argument reduction. The full machine-readable list is
`jevops.logic_refactor.reduction_catalog()`, including environment and trust notes.

| Area | Available methods | What remains bounded/conditional |
| --- | --- | --- |
| Boolean logic | Algebraic rules, K-map/QM, DNF/CNF, ROBDD, e-graphs | Bare classical propositions; at most eight atoms |
| Context/invariants | Substitution, contradiction, redundant facts, finite Houdini/reachability | Explicit finite transition model for Houdini |
| Quantifiers/logic transport | Witness distribution, negation, contraposition, iff construction | Lean checks scope and side conditions |
| Equality/normalization | `rfl`, `dsimp`, congruence, AC, controlled `grind` | No arbitrary binder rewriting in Python |
| Arithmetic | `omega`, `linarith`, `ring`, `nlinarith`, `norm_num`, positivity | Appropriate domain and imports required |
| Algebra | `abel`, `noncomm_ring`, `group`, denominator/cast normalization | Nonzero and typeclass obligations retained |
| Order | `order`, `bound`, min/max case proposals | Some tactics require Mathlib/version support |
| Finite domains | `decide`, finite-context proposals, bitvectors | Bitvector native trust explicitly distinguished |
| Sets/functions/datatypes | Extensionality, injectivity/disjointness, constructor folds | Real Lean types, not Boolean aliases |
| Proof structure | Local deletion, branch replacement, sibling/block slicing, rewrite finishing | Every resulting body recompiled in the same envelope |

Slicing is inspired by delta debugging's oracle-guided minimization, with
hierarchical structure reducing malformed trials. Here the interesting property
is **successful proof admission**, not program failure. Whole-chunk deletion can
remove dependent dead blocks that cannot be removed individually.
[Delta debugging](https://www.debuggingbook.org/html/DeltaDebugger.html),
[Hierarchical Delta Debugging](https://www.cs.ucdavis.edu/~su/publications/icse06-hdd.pdf).

`jevops.proof_slicing.minimize_checked` performs bounded, restart-on-improvement
search with compiler receipts, fixed theorem envelope and configurable token
counter. `proof_slice` also enters ordinary router rounds. Layout is not a Lean
parser; comments/opaque text are conservatively skipped and failed drafts earn
nothing. The result claims neither global nor 1-minimality.

```python
from pathlib import Path
from jevops.proof_slicing import minimize_checked
from jevops.router_tuning import _lean_compiler

source = "theorem t (h : True) : True := by\n  have a : True := h\n  exact h"
result = minimize_checked(source, _lean_compiler(project_root=Path("/tmp"), kernel_only=True),
                          max_calls=16)
assert result["ok"]
```

## 5. Training and ML kernel methods

Verified shorter proofs can teach a simplifier through expert iteration.
ProofOptimizer demonstrates this pattern with verifier-backed generated pairs;
its reported compression does not establish our small autoencoder's capability.
[ProofOptimizer](https://arxiv.org/abs/2510.15700).

New candidates enter the existing compiler-gated teacher pipeline. CE, cosine,
binding BCE, raw predictions and search winners remain separate. Failed proofs,
unproved invariants and Python e-graph equivalences are never proof targets.
Canaries and holdouts must stay outside training-teacher collection. The new algorithms
do not constitute NCA training or a demonstrated learned tactic synthesizer.

The [rewrite-distillation follow-up](REWRITE_DISTILLATION.md) now implements a
learned span-copy editor and finite GF(2) affine-invariant mining. It measures
model-only 482→481 and historical-seed 392→391 arena compression, separately
from search. The original-input CE gate fails, so the checkpoint is not promoted.
The deterministic experiment in section 7 below remains a separate historical
result; the new editor does not beat its 391-token best.

The IR recognizes 25 additional operations used by the catalog. Loading a saved
model now preserves its saved vocabulary: expanding a softmax vocabulary changes
CE even when every weight is unchanged. Training on missing operations requires
explicit `extend_operation_vocabulary()` and rebaselining; merging incompatible
vocabularies is refused. The old scalar proxy fixture is unchanged and its test
uses the historical 49-entry vocabulary for both baseline and training. Fresh
models use the expanded vocabulary. Parser/vocabulary versions must also be fixed
before comparing historical CE numbers.

If “kernel methods” also means statistical kernels, Weisfeiler–Lehman subtree
features are a promising way to retrieve structurally similar dependency graphs
without depending on binder names. The original kernel uses graph refinement
features; it is not a theorem prover or an equivalence test.
[Weisfeiler–Lehman graph kernels](https://jmlr.org/papers/v12/shervashidze11a.html).

Proposed, not implemented here: compare normalized linear/WL kernels and RBF
kernels on frozen training-only proof features for tactic ranking or compile-cost
prediction. At large scale, prefer sparse explicit features or approximate kernel
features over a corpus-wide quadratic Gram matrix. Never reward similarity as a
substitute for a proof. Compare against cheap symbol/operation-count baselines
before paying for graph kernels. Their impact on this arena is unmeasured.

The local `ipfs_datasets_py` guidance also reinforces evidence-based promotion:
separate cold/warm measurements, fixed lineage and semantic gates, and mark
unavailable causal guidance as unmeasured. Files reviewed:
`docs/implementation/reports/HAMMER_LEANSTRAL_LEGAL_IR_OPTIMIZATION_REPORT.md` and
`workspace/benchmarks/semantic-roundtrip-compositions/causal_autoencoder_guidance_qualification.json`
under `/home/barberb/lift_coding/external/ipfs_datasets`. Dry-run or terminal-
unsupported records are not evidence of training or throughput improvements.

## 6. Remaining high-value architecture work

1. Export typed Lean `Expr`/InfoTree dependency graphs with binder, universe,
   environment and source-span identities; preserve scopes across transformations.
2. Harvest solver suggestions into explicit replayable proofs, and measure term
   DAG size as well as token count and checking cost.
3. Add scoped typed equality saturation or guided `grind` schedules with proof
   reconstruction. Keep the current bare-atom Boolean engine separate.
4. Add infinite-state invariant domains with checkable certificates, rather than
   applying Boolean or sample-based reductions to arbitrary Lean programs.
5. Freeze a broader, disjoint corpus and run ablations for each method family,
   trust tier and toolchain before checkpoint promotion or throughput claims.

No new external solver or toolchain is installed automatically. No public arena
score, global proof minimum or trillion-token processing rate is claimed.

## 7. Measured local regression result

On 2026-09-22, three isolated deterministic router rounds (pool 16, 34 compile
attempts) reduced `CallElimCorrect.substOldPostSubset` from the reverified
historical local best of **392 to 391 arena body tokens**. The frozen original
has 482 tokens. This is one seeded regression theorem, not a random canary,
unseen holdout, full-benchmark improvement or official arena score.

The winning `rewrite_transport` proposal changes exactly this induction branch:

```diff
   case abs ih =>
-    exact ih
+    assumption
```

The statement prefix, binders and goal are unchanged; no helpers are added.
The candidate was independently recompiled after search using strict axiom
auditing on Lean `v4.26.0`, Strata commit
`451e5f047bafa010d178856db76c00029bfa4d7f`. Its transitive dependencies are exactly
`propext` and `Quot.sound`: no `sorryAx`, native-evaluation or project-specific
axioms. The module contains unrelated `sorry` warnings, which are preserved in
the receipt rather than hidden. The cached source was restored and its Git
status checked clean. The independent invocation took about 4.6 seconds in an
already provisioned project; this is not isolated kernel time or a cold-start
throughput measurement.

The compact [regression artifact](tests/fixtures/kernel_refactor_local_best.json)
stores both proofs, a source digest, toolchain pin, winning transformation,
model diagnostics and the independent axiom report. Its unit test rechecks the
exact edit, tokenizer counts, frozen statement and audit parsing; replaying a
stored receipt is not a fresh kernel check. The full 34-attempt receipt is local
at `/tmp/jevops-kernel-methods-TGoYvk/arena-kernel.json`.

Training was disabled, no live LLM was called, and no production memory or
checkpoint was promoted. The untrained autoencoder still emits **482 tokens**;
its separately measured CE is approximately **4.304065** and cosine similarity
**0.4885** against the verified search target. The search result must not be
reported as learned compression or an NCA training improvement.

To repeat the isolated search from the repository root, with cached pinned
projects and the historical parent Git commit available:

```bash
python papers/completion/lean_refactor_arena/harness/validate_logic_reductions.py \
  --name CallElimCorrect.substOldPostSubset --rounds 3 --pool 16 --timeout 60 \
  --kernel-only --strategy proof_slice --strategy grind_control \
  --strategy rewrite_transport --output /tmp/lra-kernel-validation-new.json
```

Use a new output path; existing receipts are never overwritten. The frozen
15-record JSONL and its SHA-256 remain unchanged:
`6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804`.

## 8. Validation

Final full suite: **266 passed**, one optional `ipfs_datasets_py` deprecation
warning, with `JEVOPS_MATHLIB_PROJECT` pointing at the built cached PhysLib
project. Core tests used Lean 4.34.0, Mathlib tests its pinned Lean 4.32.0, and
the arena result the separately pinned Lean 4.26.0 above. No toolchain was
downloaded or substituted for the arena pin.

Coverage includes exhaustive truth tables for each e-graph rule, randomized
bounded extraction, maximum-depth extraction, Houdini fixed-point/removal
counterexamples, mutual invariant support, dead-block slicing, strict rejection
of native/custom/transitive-sorry axioms, source restoration on compile failure,
historical vocabulary CE consistency, and refusal of incompatible training
batches before any weight update. The real Mathlib test compiles 16 solver
fixtures and rejects a false denominator-cancellation statement.

In addition, a separate real Lean batch proved all **29** e-graph rewrite
equivalences using classical case splits, with strict audits permitting only
`propext`, `Classical.choice` and `Quot.sound`. That validates the fixed Boolean
rules, not arbitrary future rules, Python extraction code or dependent Lean
expression rewrites; every generated refactoring still needs its own compile.

```bash
JEVOPS_MATHLIB_PROJECT=/path/to/built/mathlib-project python -m pytest -q
```

Without the optional project, the Mathlib test is skipped. Lean-dependent tests
also skip if Lean is unavailable; such a run must not be reported as real-kernel
validation. `git diff --check` passed.
