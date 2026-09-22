# JevOps

TypeSafe / Jev **kernel**, split from Lean Refactor Arena and other papers.

The Jev kernel is a **gate**, not a proof authority. Optional refactoring and
autoencoder modules propose Lean candidates; only the consuming Lean/Lake
verifier can admit them. The generic kernel keeps that verifier injectable.

## Layout

| Module | Job |
| --- | --- |
| `jevops.hooks` | Optional consumer callbacks (`load_board`, `token_count`, …). Kernel never requires them. |
| `jevops.nca` | Cell store, tick/halt, inspect_python, mutate overlay, dispatch_tool |
| `jevops.walk` | Inner loop, compose dispatch, ptr CALL, nest/spawn, admit_step |
| `jevops.board` | Generic goal/subgoal/task grid seed, status overlay, mark_ready |
| `jevops.outer` | Outer JSON actions, `run_steps` / `route_next`, stall/stop |
| `jevops.oracle` | Candidate order, try_kind / apply_round / pack_eval |
| `jevops.pick` | Jev beam, leftover rank, shorter_bag, sample/filter records |
| `jevops.memory` | Success/failure/blacklist/research JSON memory, gap_report |
| `jevops.jev` | Choice/Score/Noul projectors, truncate_middle, FixtureClient |
| `jevops.kernel` | L0–L3 cache, CID, ARC/LRU, negative TTL, single-flight, context budget |
| `jevops.tape` | Neural tape (window, splice, mask, pop, byte trim) |
| `jevops.stack` | `ptr://` CALL/RETURN stack |
| `jevops.jsonld` | JSON-LD graph interface; DuckDB optional |
| `jevops.plan` | Goal / subgoal / task DAG + graph-of-thoughts |
| `jevops.graph` | Traverse, GraphRAG (JSON-LD first), milles message-pass |
| `jevops.skill_tree` | Hierarchical skill catalog |
| `jevops.rankers` | RF / Bayes-time / MCMC / SVD dispatch |
| `jevops.int_rankers` | Integer milles rankers |
| `jevops.more_rankers` | Markov / isotonic / AdaBoost / PageRank / contrastive |
| `jevops.temporal` | Hawkes / CRF / submodular / delayed bandit / tape conv |
| `jevops.tactics` | Lean tactic analysis plus explicit multi-armed-bandit action tactic |
| `jevops.autoencoder` | Canonical Lean IR, sparse trainable autoencoder, verifier-gated rewards |
| `jevops.autoencoder_training` | Cross-entropy/cosine training, LR schedule, canary/holdout protocol |
| `jevops.logic_ir` | Bounded propositional IR, K-map/Quine–McCluskey minimization, BDDs and invariant obligations |
| `jevops.logic_refactor` | Compiler-gated logic/arithmetic/structural reduction catalog and rotating sweeps |
| `jevops.program` | Closed IR compile/parse, work-ops execute (lake/board via hooks) |
| `jevops.repair` | Diagnose/heal grid, tape, stack, program_state |
| `jevops.tools` | TypeSafe tool catalog, MCP++ describe, subloops, KG |
| `jevops.harness` | Inner JevOps self-analysis + outer `llm_router` autoresearch gate |
| `jevops.proof_ca` | Proof-carrying typed ground-Horn graph cellular automaton |
| `jevops.proof_ca_demo` | Offline JSON trace and matched scheduling benchmark |
| `jevops.turing` | TM step/run + decision-transformer window |
| `jevops.tape_tools` | Tape editor CALLs (`port_tape_*`) |

## Skills

Grok skills live in `skills/` (canonical). LRA keeps thin `lra-*` redirects.

| Skill | Module |
| --- | --- |
| `jevops-hooks` | `jevops.hooks` |
| `jevops-kernel` | `jevops.kernel` |
| `jevops-nca` | `jevops.nca` |
| `jevops-tape` | `jevops.tape` / `tape_tools` |
| `jevops-stack` | `jevops.stack` |
| `jevops-skill-tree` | `jevops.skill_tree` |
| `jevops-walk` / `jevops-compose` | `jevops.walk` |
| `jevops-intent` | `jevops.jev` / `pick` / `walk` |
| `jevops-pick` | `jevops.pick` |
| `jevops-jev` / `jevops-redact` | `jevops.jev` |
| `jevops-oracle` | `jevops.oracle` |
| `jevops-outer` | `jevops.outer` |
| `jevops-memory` | `jevops.memory` |
| `jevops-repair` / `jevops-indent` | `jevops.repair` |
| `jevops-program` | `jevops.program` |
| `jevops-tools` | `jevops.tools` |
| `jevops-board` | `jevops.board` |
| `jevops-jsonld` | `jevops.jsonld` |
| `jevops-random-forest` / `jevops-bayes-time` / `jevops-mcmc` / `jevops-svd` / `jevops-ridge` / `jevops-thompson` | `jevops.rankers` |
| `jevops-int-rankers` / `jevops-pca` | `jevops.int_rankers` |
| `jevops-more-rankers` | `jevops.more_rankers` |
| `jevops-mask` / `jevops-mca` / `jevops-spans` | `jevops.mask` |
| `jevops-search` / `jevops-fills` | `jevops.search` / `jevops.mask` |
| `jevops-ast-rewrite` | `jevops.nca` |
| `jevops-autoencoder` | `jevops.autoencoder` |
| `jevops-graph` | `jevops.graph` |
| `jevops-temporal` | `jevops.temporal` |
| `jevops-turing` | `jevops.turing` / `tape` / `tape_tools` |
| `jevops-plan` | `jevops.plan` |

## Consumers

See [Logic reductions](LOGIC_REDUCTIONS.md) for the reduction catalog, limits,
proof obligations, and integration with router/autoencoder training.

Lean Refactor Arena harness re-exports these as `nca_kernel`, `nca_plan`, `typesafe_nca` cell helpers, etc.
Set `JEVOPS_CAS_DIR` for L2 CAS (LRA sets it to `evidence/canaries/nca-cas`).

Register implementation hooks instead of importing paper modules from the kernel:

```python
from jevops import hooks
hooks.register("load_board", my_board_loader)
hooks.register("token_count", my_token_count)
```

If hooks are missing, the kernel `try_import`s consumer modules that happen to be on `PYTHONPATH` (LRA harness). Missing hooks fail closed.

## Dependency boundary and deprecation

This checkout has no Git submodule entry and does not require the separate
Endomorphosis `ipfs_accelerate` or `ipfs_datasets` repositories for its core
runtime. The small interfaces JevOps actually uses are now in-tree:

* `jevops.typesafe_inference` is the stdlib-only structured TypeSafe client;
* `jevops.llm_router` supplies deterministic offline, Codex CLI, and
  OpenAI-compatible HTTP routes;
* local JSON-LD, SQLite, and symbolic fallbacks remain the normal graph and
  receipt paths.

The old external repositories are compatibility inputs, not core
dependencies. `JEVOPS_USE_EXTERNAL_ROUTER=1` selects the deprecated
`ipfs_accelerate_py.llm_router`; `JEVOPS_USE_EXTERNAL_DEPS=1` enables the
deprecated optional datasets/accelerator adapters. Those paths emit
`DeprecationWarning`, are never silent proof authorities, and can be removed
after downstream consumers migrate. DuckDB, NumPy, and Lean/Lake remain
optional adapters/toolchains; they are not copied into this Python package.

## Two-level autoresearch loop

`jevops.harness.JevOpsHarness` runs a bounded inner/outer loop. The inner
iteration analyzes the JevOps source tree and updates AutoResearch memory; the
outer iteration calls the in-tree `jevops.llm_router.generate_text` facade for
a closed JSON action. `update_code` proposals use exact `old`/`new` text, are
evaluated in a temporary repository copy, and are applied only when the
injected evaluator improves (`score` is higher-is-better and `ok` must be
true).

```python
from jevops.harness import JevOpsHarness

harness = JevOpsHarness(
    root="/path/to/JevOps",
    evaluate_fn=lambda root: {"ok": True, "score": run_my_harness(root)},
)
receipt = harness.run(iterations=4)
```

The default is fully offline and deterministic:

```bash
python -m jevops.harness --iterations 4
```

For a real model, select an in-tree provider explicitly. The Codex CLI route
does not require the accelerator checkout:

For a bounded command-line run:

```bash
python -m jevops.harness --iterations 4 \
  --provider codex_cli --model gpt-5.6-luna --reasoning-effort high --strict-router
```

For a continuously supervised run, use `--continuous`. Each cycle performs
the inner self-analysis, asks the configured router for one closed action, and
persists memory plus a JSONL receipt. `--strict-router` prevents silent
cross-provider fallback; `update_code` is still applied only after the
isolated evaluator improves.

```bash
python -m jevops.harness --continuous --interval 60 \
  --provider codex_cli --model gpt-5.6-luna \
  --reasoning-effort high --strict-router
```

The TypeSafe provider is a structured System One evaluator, not a free-form
text generator. Keep its credential in `TYPESAFE_API_KEY` when TypeSafe gates
are used. Existing consumers that still require the external route may set
`JEVOPS_USE_EXTERNAL_ROUTER=1` and `JEVOPS_IPFS_ACCELERATE_PATH`, but that
compatibility path is deprecated.

### Router-guided proof tuning

`jevops.router_tuning.RouterTuningLoop` is the proof-specific router loop. It
asks the configured `llm_router` for bounded IR/tactic suggestions, expands
allowlisted local tactic families, compiles every candidate once, and trains
the Lean IR autoencoder only from the verified winner. The default route is
`provider="codex_cli"`, `model_name="gpt-5.6-luna"`, and strict
cross-provider fallback is off. The router is advisory; Lean/Lake remains the
admission authority and verified proof-body token count is the primary search
key. Strict mode also checks `llm_router`'s effective provider/model trace and
fails closed on a silent fallback; each round records that route attestation.
Training receipts distinguish the actual autoencoder `loss` from the verified
candidate's `candidate_target_loss`, so a perfect target match cannot masquerade
as a perfect model prediction. Results also expose `model_body_tokens_after`
separately from the verified-search `best_body_tokens`.

The search performs two bounded composition passes. The first crossovers the
current round's verified teachers; when that pool matches or improves the
previous elite, a second `max_elite_composed_candidates` pass composes the new
router/hammer/local/model teachers with older verified teachers. Derived
composition and IR-crossover rows are excluded as parents in the second pass,
and every candidate remains compiler/Lake-gated with parent provenance.

```python
from jevops.router_tuning import RouterTuningConfig, tune_autoencoder_with_router

result = tune_autoencoder_with_router(
    memory,
    theorem_source,
    problem="my-theorem",
    compile_fn=lake_compile,
    config=RouterTuningConfig(rounds=3, model_name="gpt-5.6-luna"),
)
```

For a standalone file, the bounded CLI is:

```bash
python -m jevops.router_tuning theorem.lean --lake \
  --provider codex_cli --model gpt-5.6-luna --rounds 3
```

The router-specific offline tests are `pytest -q tests/test_router_tuning.py`;
they inject a fixture router and never require router credentials.

## Lean IR autoencoder training

The autoencoder has two separate contracts:

* `encode_lean_ir` / `decode_lean_ir` use a deterministic, argument-preserving
  Lean IR (`jevops-lean-ir/v2`) and reject admitting or command-smuggling text.
* `train_autoencoder` trains a JSON-safe sparse model with teacher-forced
  operation cross-entropy, cosine-aware latent updates, gradient clipping,
  warmup/cosine/plateau learning-rate control, NCA auxiliary feedback, and
  bounded reward signals.

Lake/LRA remains the hard proof authority. TypeSafe/JeV can rank candidates or
provide soft fuzzy theorem-plausibility signals, but an unverified candidate
cannot enter the verified codebook. `minimality_score` rewards shorter
candidate equations only after semantic/proof gating. Training creates disjoint `train`, `validation`, `canary`, and
`holdout` assignments from a content-addressed manifest. The canary is a
regression gate, not an epoch-selection target; the holdout is not evaluated
until `evaluate_frozen_holdout` is called explicitly.

```python
from jevops.autoencoder import (
    AutoencoderConfig,
    evaluate_frozen_holdout,
    train_autoencoder,
)

config = AutoencoderConfig(seed=17, validation_fraction=0.1,
                           canary_fraction=0.1, holdout_fraction=0.1)
report = train_autoencoder(records, config=config, epochs=3,
                           compile_fn=lake_compile)
# Seal report["state"] and report["manifest"] before reading the holdout.
holdout = evaluate_frozen_holdout(report["state"], records,
                                  manifest=report["manifest"])
```

The implementation is dependency-free; a consumer can replace the sparse
backend with a vectorized/Torch trainer while retaining the same state,
metric, verifier, and holdout contracts.
For corpus-scale ingestion, `train_autoencoder_stream` accepts a
split-aware factory and never requests the `holdout` split during training.
Pass the training `memory` (or evaluator `nca_memory`) to use NCA cell energy,
neighborhood, residual-help, and historical verifier feedback as a bounded
auxiliary signal. `typesafe_fuzzy_prove` uses typed Choice/Score/Noul
questions as a fuzzy advisor; its result is always marked unverified and must
be followed by Lake compilation.
Disjoint workers can call `merge_model_states` to combine bounded sparse
checkpoints without gathering the corpus or retaining source text centrally.
For the integrated path, `refactor_smallest(...)` composes TypeSafe fuzzy
ranking, NCA feedback, Lake admission, and minimality selection in one call.
The offline three-round regression is `pytest -q tests/test_autoencoder_rounds.py`;
it invokes the installed Lean executable and compares against
`tests/fixtures/autoencoder_score_baseline.json`. That score is a frozen local
training proxy, not an official Lean Refactor Arena leaderboard result.
The same test also runs four deliberately compressible theorems through three
training rounds. Its shortest-proof proxy counts verified proof-body tokens,
keeps the pre-shrink result in
`tests/fixtures/autoencoder_smallest_baseline.json`, and requires every
shortening to pass Lean before it can win. The current local proxy is
`0.7797619047619048` versus the frozen pre-shrink `0.125`; neither is an
official Arena score.

For an isolated check of **learned** shortening rather than search success, run:

```bash
python -m jevops.training_probe --output /tmp/jevops-training-probe-new.json
```

This trains a fresh model on four compiler-checked synthetic deletion pairs,
then evaluates its actual rendered predictions on two held-out development
fixtures, a live-binding negative control, and eight randomized dependency
fixtures. It never uses arena data or production memory. The receipt includes
CE/cosine, compiler outcomes, the checkpoint, and separate **raw** and
dependency-guarded predictions. The raw model still deletes necessary bindings;
the conservative guard restores prerequisites or suppresses uncertain edits.
That is static protection, not learned dependency reasoning or evidence of
arena generalization. That is the default legacy experiment. To train the
opt-in binding keep/delete head on a balanced curriculum, run:

```bash
python -m jevops.training_probe --curriculum balanced --train-binding-policy \
  --output /tmp/jevops-binding-probe-new.json
```

This learns binary-classifier weights over **symbolic source dependency
features**. It reports binding BCE separately from sequence CE/cosine, along
with raw-head, guarded and old-decoder ablations. On 11 development fixtures,
the raw head produced four shorter, compiler-valid proofs without guard
restoration; the same-weights old decoder shortened none. Unsupported proof
structure is preserved, not compressed. That checkpoint's arena search tied
392 tokens; it did not improve the previous best and is not promoted. The router
can opt in with `RouterTuningConfig(train_binding_policy=True)` or
`--train-binding-policy`; raw proposals still require Lean admission. Canary
checks also reject binding-loss, verification and metric-coverage regressions.
See [validation details](LOGIC_REDUCTIONS.md).

For the expanded 28-family reduction catalog, bounded equality saturation,
Houdini invariant inference, proof slicing and strict axiom-audit mode, see
[kernel/refactoring research and implementation](KERNEL_REFACTORING_RESEARCH.md).
The report distinguishes implemented algorithms, optional Lean/Mathlib solver
proposals and remaining typed-expression/large-scale research work.

## Action bandits and the neurosymbolic CA

`jevops.tactics.multi_armed_bandit` is the action-level policy primitive. A
selection creates one pending pull; a later call supplies the measured reward
in `[0, 1]` (or a Boolean). The tactic stores Beta/UCB statistics under
`memory["nca"]["bandits"]`, mirrors the action and outcome into `ptr://cell`
and `ptr://skill` cells, and journals the transition. It never treats a
selection as a proof or code admission.

```python
from jevops.tactics import multi_armed_bandit

pick = multi_armed_bandit(memory, ["port_simp", "port_cases"], seed=7)
# After the lake/evaluator measures pick["selected_arm"]:
next_pick = multi_armed_bandit(memory, ["port_simp", "port_cases"], reward=0.9)
```

The existing `port_thompson` ranker remains a pipeline-order heuristic. Use
the action bandit when a loop needs a real select→measure→update lifecycle.
The current NCA is a useful substrate—canonical cells, energy diffusion,
board edges, tape/stack receipts, and symbolic gates—but it is not yet a full
cellular automaton: the next architectural step is a synchronous, typed local
transition rule that consumes a cell state plus bounded neighbor messages and
emits a validated state delta. Keep Lean/Lake and evaluator receipts as the
symbolic authority for those deltas; keep the outer router responsible only
for bounded proposals.

## Proof-carrying graph cellular automaton

The strict symbolic runtime is in `jevops.proof_ca`. It uses a declared finite
universe of ground atoms and immutable positive Horn rules. Rule cells have
typed premise and conclusion edges; conjunction is checked by exact premise
identity, not by votes, activation averages, or incoming-edge counts. A fact
can enter the accepted set only as a declared assumption, a checked local rule
derivation, or a context-matched verified external receipt.

Run the complete offline example and benchmark with:

```bash
python -m jevops.proof_ca_demo
```

The command emits a JSON proof trace, an injected mock-verifier receipt, and a
matched comparison of a deterministic queue, a centralized controller using
the same action interface, and the local fair scheduler. It makes no API calls
and reports measured synthetic work only; `actual_cost` is `null` because no
paid service is used.

The runtime keeps symbolic, policy, evidence, and operational state separate.
`JevPolicyAdapter` is dependency-injected and receives only a bounded local
snapshot. Its selected value, distribution, confidence, question version, and
model identity are retained as non-authoritative observations. The deterministic
baseline is explicitly labelled a fixture. A periodic FIFO service guarantees
that a defer/rejecting policy cannot permanently suppress an enabled rule in
an unbounded run. Messages, proposals, evidence IDs, reservations, and
checkpoints are idempotent.

Final statuses are precise: `VERIFIED_COMPLETE` means all required targets
have checked supporting evidence; `QUIESCENT_INCOMPLETE` means closure with an
unproved target; `BUDGET_EXHAUSTED` means an explicit integer resource limit
blocked more work; `ERROR` means a runtime invariant or required adapter failed.
An absent verifier, timeout, test result, cache hit, activation value, or
legacy `theorem_ok` field is not silently promoted to proof. The initial
language is intentionally finite, ground, positive, and single-process; it is
not arbitrary theorem proving, distributed execution, learned neural dynamics,
or a claim about the truth of its trusted assumptions.

The invariant argument and its assumptions are documented in
`PROOF_CARRYING_NCA.md`.

## Not in this package

Portable Lean folds, `lake env`, random canaries, Track 1/2, LRA `tasks.json`
board, and the implementation-specific inner TypeSafe lake walker remain
consumer/toolchain concerns. The TypeSafe HTTP DTO/client itself is now
available in `jevops.typesafe_inference`; it remains an optional network
service, not a proof authority.

## Lean Refactor Arena benchmark integration

The frozen 15-problem warm-up corpus and the executable harness are under
`papers/completion/lean_refactor_arena/`. The harness keeps statement-prefix
binding, tag-pinned Lake compilation, `sorryAx` rejection, retained failures,
and null official-score fields. The experimental
`harness/autoencoder_bridge.py` connects those records to the router-guided
text → Lean IR → text loop; it reports the verified search winner separately
from the model's own prediction and its cross-entropy/cosine diagnostics.

```bash
python papers/completion/lean_refactor_arena/harness/run_warmup.py --plan
python papers/completion/lean_refactor_arena/tools/verify_lra_batch.py --schedule
python papers/completion/lean_refactor_arena/harness/autoencoder_bridge.py --plan
```

These commands are unscored protocol checks. A full run requires the listed
source clones and every pinned toolchain/cache; missing infrastructure stays a
failure and never becomes a PATH-Lean or Arena-score fallback.
