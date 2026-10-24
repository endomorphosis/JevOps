# JevOps Lean refactoring research and execution plan — 24 October 2026

This campaign seeks the shortest **verified** Lean proof found within a declared search budget. The primary engineering objective is proof token length, subject to unchanged theorem meaning, permitted axioms and successful checking on every required project/version. Heartbeats, compatibility, wall time and expenditure are measured separately. No finite experiment establishes a globally shortest proof.

The executable graph is [goals.json](lean_refactor_arena_20261024.goals.json), its supervisor source is [the taskboard](lean_refactor_arena_20261024.todo.md), and acceptance policy is [objectives](lean_refactor_arena_20261024.objectives.md). These files supersede assumptions about available hardware in earlier plans; historical experiment results remain historical evidence.

## 1. What the current checkout and host support

The current host is `fent-reactor`: two separate 24 GiB RTX 3090 GPUs, approximately 126 GiB RAM and 56 logical CPU threads. It is not the previously mentioned DGX Spark. Lean and Lake are installed through Elan; the observed Lean is 4.31.0. A concurrent municipal-data job and heavily used swap make bounded memory use necessary. Old prepared Arena project directories referenced by September reports are absent on this host. Their old receipts cannot certify a new run.

Local history contains a fifteen-problem, five-source schedule with 36 project/version checks. The latest historical full-matrix report checked 26 of 36 pins and fully checked nine of fifteen problems; ArkLib source/commit binding and Putnam import/toolchain issues require repair. These are infrastructure failures, not evidence that a candidate theorem is false. Existing portfolio reports include a 166-token candidate with a small heartbeat increase and a faster 168-token alternative. Rechecking them is baseline work, not a new optimization result.

Prior typed-premise and dynamic-subgoal retrieval pilots changed suggestions but produced no shorter accepted proof. Explicit proof-term replay previously retained the same four-token length. This directs new effort toward compiler-guided support minimization, dependent edit repair and controlled context experiments. It does not establish that retrieval cannot help another cohort.

Run JLR-001 for an actual time-stamped inventory. JLR-005 captures the local schedule. JLR-010 is a real Lean 4.31 smoke check on a deliberately non-Arena theorem: successful smoke checking does not repair or validate missing benchmark projects.

## 2. Research methods worth testing

The following are research motivations. Their proposed application to JevOps is an engineering hypothesis, not a reproduced result or a promised score.

| Primary source | Relevant method | JevOps experiment and control |
| --- | --- | --- |
| [Lean Refactor, arXiv:2605.20244](https://arxiv.org/abs/2605.20244) | Objective-conditioned refactoring, version-aware strategy retrieval and multiple optimization targets. | Frozen-model source/goal prompts versus the same prompts with version-filtered strategy examples, at equal native-check and generation budgets. Keep shortest-length and official-score portfolios distinct. |
| [ImProver, arXiv:2410.04753](https://arxiv.org/abs/2410.04753) | Iterative improvement with Lean context and feedback. | Maintain a verified incumbent, propose bounded edits, feed back actual compiler errors and accept only independently checked improvements. Compare with one-shot generation. |
| [ProofOptimizer, arXiv:2510.15700](https://arxiv.org/abs/2510.15700) | Optimization using verified trajectories and iterative learning. | First collect authentic improving/non-improving edit outcomes. Consider training only after frozen inference establishes a measurable error pattern and usable data. |
| [LeanDojo, arXiv:2306.15626](https://arxiv.org/abs/2306.15626) | Accessible-premise retrieval and evaluation splits. | Filter premises by actual imports, version and scope; compare lexical, typed-head and embedding rankings with hard negatives from the same project. |
| [COPRA, arXiv:2310.04353](https://arxiv.org/abs/2310.04353) | Search with execution feedback and backtracking. | Bounded branch search, deduplicated by source/environment identity. Count rejected branches and their compiler costs. This is a search policy, not a correctness oracle. |
| [Lean Copilot, arXiv:2404.12534](https://arxiv.org/abs/2404.12534) | Suggestions integrated with proof state and retrieval. | Compare goal-state suggestions with source-only editing; distinguish tactic discovery from the final compact proof. |
| [DeepSeek-Prover-V2, arXiv:2504.21801](https://arxiv.org/abs/2504.21801) | Subgoal decomposition. | Consider only after inexpensive local shortening fails; include all helper/decomposition overhead and recheck the final target in the original environment. |
| [BART, arXiv:1910.13461](https://arxiv.org/abs/1910.13461), [T5, arXiv:1910.10683](https://arxiv.org/abs/1910.10683) | Denoising and span corruption objectives. | Lean-aware span infilling or edit ranking with parser, binder and dependency metadata. Compare against lexical ranking and deletion; reconstruction loss alone is not a Lean success measure. |
| [LoRA, arXiv:2106.09685](https://arxiv.org/abs/2106.09685), [QLoRA, arXiv:2305.14314](https://arxiv.org/abs/2305.14314) | Adaptation with fewer trainable parameters and quantized frozen bases. | Optional small-model adapter only after a real memory smoke and frozen held-out evaluation. Published results do not establish that this 119B architecture fits training on this machine. |
| [egg, arXiv:2004.03082](https://arxiv.org/abs/2004.03082) | Equality saturation and cost-directed extraction. | A later narrow, typed, proof-producing term-rewrite arm. An external e-graph equality is insufficient: Lean must check the extracted proof. |

First implement the inexpensive deterministic portfolio: remove redundant wrappers, use exact existing terms, minimize `simp only` support and specialize discovered tactics. Profile expensive proof spans before changing them. Isolated deletion often fails because a later induction hypothesis or binder depends on the removed context; compare deletion alone with coupled deletion-and-repair. Preserve original source ranges and dependencies so edits cannot silently target a different theorem.

Search scripts may be long while exploring. Extract a short final tactic invocation or explicit proof term only when supported by the actual pin. Never introduce a Mathlib tactic into a Core-only environment by importing a new library. Keep the existing tactic-support matrix and version-aware replay. Any helper declarations and imports must follow the organizer's cost and target contract; uncounted helper code is not valid compression.

## 3. Correctness includes computational behavior

The trusted acceptance boundary is a fresh, complete-source check against exact Lean, Lake, dependency and source pins. Preserve the theorem statement, binders, universe parameters, target identity, imports, namespace and source prefix. Inspect the elaborated type and axiom dependencies. Reject `sorry`, `admit`, unsafe escape paths, new axioms, circular target references and unapproved native-evaluation trust extensions. Compare candidate axioms against the actual permitted reference set, rather than a hard-coded list from a different Lean version.

[Lean's proof validation documentation](https://lean-lang.org/doc/reference/latest/ValidatingProofs/) explains the kernel/trust boundary. Native-evaluation trust changed in recent Lean versions; do not assume an older `Lean.ofReduceBool`-only filter covers current `_native` declarations. Audit the pinned toolchain and the actual dependency closure. [Lean's axioms documentation](https://lean-lang.org/doc/reference/latest/Axioms/) informs the policy, not a blanket ban on legitimate classical reference axioms.

Lean's [propositions documentation](https://lean-lang.org/doc/reference/latest/The-Type-System/Propositions/) describes proof irrelevance and erasure. That supports changing a proof of an unchanged proposition; it does not certify a rewritten executable definition. Any future definition refactor requires a checked extensional/equivalence theorem plus runtime regression checks for relevant inputs and resource behavior. Keep this separate from proof-only Arena work. Numeric or floating-point results need a stated equality/tolerance specification; do not substitute an embedding similarity score.

Cache identities include exact source bytes, target/prefix, compiler and dependency commits, imports, all required pins, measurement options, policy version and producer/verifier hashes. Changing any dimension invalidates reuse. Validation receipts bind the actual source and observed outcomes. A model-generated `verified: true`, a successful subprocess exit without proof records, an existing file or a low reconstruction loss cannot complete a scientific task.

## 4. Leanstral: frozen inference first

The [Leanstral 1.5 model card](https://huggingface.co/mistralai/Leanstral-1.5-119B-A6B) describes a public Apache-2.0 mixture-of-experts model with approximately 119B total and 6.5B active parameters. Active parameters affect per-token work; total weights still need storage. BF16 weights alone are roughly 222 GiB, and conventional full training with gradients and optimizer state is substantially larger. Full fine-tuning is disabled for this campaign. The user's clarification authorizes downloading and using inference on the current host.

A pinned community Q4_K_M GGUF is 72,159,246,080 bytes, approximately 67.2 GiB. The provisioner records the repository revision, full SHA256, license, runtime assets and observed GGUF architecture. A community quantization is a derivative artifact: do not imply a checksum proves equality with the unquantized official weights. No smaller compatible quantization has yet been qualified. Do not silently replace it with pruned or hardware-incompatible weights.

Provisioning uses an isolated `llama.cpp` runtime with two recognized CUDA devices, localhost port 18180 and a new owned service. Initial limits are context 2048, batch 64, microbatch 32, up to eight CPU threads and 18 GPU-offloaded layers split across the two cards. The remaining weights stay in CPU RAM. Require sufficient preload memory, retain at least 16 GiB host available memory while running, enforce server RSS at most 48 GiB and GPU use at most 20 GiB per card. A cgroup also limits memory, swap, CPU and process count. Resource violations stop only the campaign's owned service.

Validate complete size and SHA before loading; then verify health, advertised model identity, actual memory use and a short generation. A sixteen-token `rfl`-style protocol probe establishes that inference responds; it is not proof optimization. Historical port-8080 URLs returned unqualified HTML and are not reused as healthy Leanstral endpoints.

After native benchmark projects are ready, start with two requests, at most 1024 input plus 256 output tokens per request, 90 seconds each and 240 seconds total. Compare exact original proof, goal-state context and version-filtered retrieved context. If a source does not fit, select authenticated relevant spans or skip with a reason; do not silently truncate the theorem statement. Record quantization, prompt template, sampling, all failures, latency and native-check costs. Expand context only after an actual memory/quality experiment.

## 5. Reuse the autoformal/encoder approach carefully

Useful existing interfaces include `jevops/autoencoder_training.py`, the frozen harness `autoencoder_bridge.py`, and Datasets' `logic/formalization/autoencoder` source-custody and embedding utilities. Read applicable directory instructions before modifying them. Reuse data provenance and bounded inference interfaces rather than assuming that legal-domain embeddings or weights understand Lean proofs.

Represent a Lean span with exact source hash, byte offsets, parser category, binders in scope, imports, target type, goal/hypotheses, accessible premises, project/toolchain pins and candidate edit. Preserve its source custody and invalidation rules. Cached 768-dimensional embeddings may be reused only with authenticated model/source identities; a cache miss must not trigger an unbudgeted model load. The existing device utility's bounded batch and deadline are useful patterns.

Create records from actual native outcomes: improving edits, valid non-improving edits, compiler/type errors and infrastructure failures as separate classes. Exclude environment failures from semantic negative labels. Split by theorem family, aliases, dependencies and project before fitting. Deduplicate near-identical proofs across versions and keep public warmup data in development. Seal holdout manifests and never rank or tune against their labels.

Start with the existing lightweight CPU sparse encoder: 256 hashed features, latent dimension 16, input limit 512, batch eight and two CPU threads. A pilot is two arms of 32 updates, at most 600 seconds and 4 GiB RSS per arm. Compare a lexical baseline at equal retrieval and compiler budgets. Count the encoder's actual decoded/ranked output; do not report the teacher-selected best edit as the student's prediction. Prior reconstruction studies or equal-argmax compression results are not a demonstrated Lean shortening gain.

Promotion needs a frozen held-out gain in verified token reduction or accepted-candidate efficiency, measured across disjoint families, without weaker axiom or compatibility checks. Report all attempts, confidence intervals or paired case outcomes where meaningful, memory, wall time and calls. A neutral result should retain the simpler lexical or frozen-model system.

Only if measured failures justify adaptation, consider a licensed framework-compatible 1–3B trainable base with LoRA rank eight, alpha 16, dropout .05, sequence 512 and batch one/accumulation eight. First require a five-minute memory smoke within one available GPU; then at most 100 steps/1800 seconds before freezing one checkpoint for evaluation. This is an optional later gate, not automatic training. GGUF inference support does not imply availability of compatible training weights or a supported QLoRA backend for Leanstral.

## 6. Metrics, current competition rules and controls

The current [Arena application](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/blob/main/app.py) and [leaderboard implementation](https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena/blob/main/leaderboard.py) are the source for current rules and scoring. Recheck before submission. As observed on 24 October, the full fifty-problem release is announced for 1 November, with a deadline of 8 November. The present UI lists a newer six-source cohort; the local fifteen-case/five-source corpus is historical. JLR-035 creates a new versioned release inventory rather than quietly replacing old denominators.

Official scoring combines token reduction, heartbeat reduction and compatibility, with missing/invalid cases contributing zero over the full cohort. Use fixture parity with the actual implementation, including rounding and absent heartbeat baselines. Do not present the user’s length-first objective as identical to the official combined score. Retain three reports: shortest admissible proof, strict dual-improvement control and official-score/Pareto portfolio.

The closed track currently requires every model call through OpenRouter and a US$3 per-problem cap. The requested Grok CLI route is development orchestration and is **not** an eligible closed-track run. A later track-specific route needs actual usage/list-price accounting including failed calls, retries and retrieval/planning calls. The open track requires public weights and reproducible inference within four 80 GiB A100 GPUs and 48 hours. Proprietary Grok development assistance must not become an undeclared call inside a claimed open-model inference pipeline. Local 3090 execution does not attest organizer hardware runtime.

For each problem record original and candidate tokens, raw heartbeats per exact pin, checked/required pins, compiler classifications, calls/input/output tokens, financial cost where applicable, wall time and peak CPU/GPU memory. Freeze candidate winners before confirmation to avoid selection bias. Use matched compiler budgets and balanced original/candidate order; repeat noisy finalists at least three paired times. Keep unchanged original proofs as valid fallback. Do not omit unresolved projects from the whole-corpus denominator.

## 7. Goals, phases and executable tasks

The graph contains ten goals and 38 tasks. Fifteen bootstrap tasks are executable now; 23 research work packages are explicitly `planned`. Planned tasks are ingested for dependency and coverage checks but cannot be selected or credited as complete. Their reviewed producer commands, protected native validators, environment/resource identities and activation receipts must be materialized before execution. Describing an experiment is not implementing or running it.

| Goal | Concrete sequence | Exit gate |
| --- | --- | --- |
| G001 orchestration | 001 inventory; 002 actual routed review | Fresh source-bound strict provider/model evidence |
| G002 semantics/metrics | 003–009 protocol/scorer/policy/cache checks | Offline fixtures and adversarial module tests pass |
| G003 native environments | 010 actual smoke; 016–018 exact projects/baselines | Every claimed benchmark pin checked against current source |
| G004 deterministic refactoring | 019–022 support minimization, coupled repair, extraction, portfolio | Fresh whole-source all-pin proof evidence |
| G005 frozen Leanstral | 013 design; 023–025 runtime qualification and bounded ablations | Authenticated runtime plus independently verified candidate results |
| G006 spans/encoders | 011–012 design; 026–029 provenance, disjoint data, CPU controls | Held-out verified benefit at matched budgets |
| G007 training decision | 014 design; 030–032 conditional adapter work | Resource, trainable-base and evaluation gates; full training disabled |
| G008 resilience | 015 review; 033–034 owned fault tests and activation | Bounded recovery and honest capability waits |
| G009 evaluation/release | 035–038 cohort refresh, evaluation, report and review | Track-eligible budgets, reproducible manifests and explicit submission decision |

Immediate router coding tasks implement small **advisory** Python policies: strict proof-result predicates, length-first candidate selection and exact-source/context cache hashes. Protected deterministic tests, not the model, decide acceptance. These modules consume actual verifier records; they do not themselves prove Lean theorems. Other router bootstrap outputs are schema-checked design proposals. Completing one means a review artifact exists with a valid route receipt, not that its proposed experiment succeeded.

## 8. Supervisor operation and recovery

The profile is `config/lean_refactor_arena_20261024_supervisor.json`; the dedicated lane manifest is `config/lean_refactor_arena_20261024_lanes.json`. The namespace is `jevops-lean-refactor-20261024`. Existing VDG/VOG lanes and unrelated jobs retain ownership of their resources. The launcher calls the real supervisor parser and plan checker before acquiring a lifetime ownership lock and handing readiness to the lane process. It starts a separate guardian and retains process/heartbeat reports.

Every Grok task calls `tools/run_lean_refactor_router_task.py`, which uses the IPFS accelerator's actual `LlmRouterInvocation`/`call_llm_router_with_receipt` path. Provider `grok_cli`, model `grok-4.7`, low reasoning effort, effective-provider trace and no fallback are mandatory. A raw CLI argv with an unspecified model is not accepted as this route. Closed response schemas, exact output allowlists, baseline hashes and inode/byte checks protect against stale overwrites. The model cannot edit the board, validators, supervisor configuration, credentials or trusted execution receipts.

Initial limits: one task at a time, 24 router calls total, at most three per task, 120 seconds per provider call, at most 4096 output tokens and four hours per owner. The guardian itself makes no model calls. Dependencies, bounded task timeouts, attempt ceilings and cooldowns prevent endless re-selection. A failed provider or native environment remains a classified failure with evidence; it never becomes a fake successful proof.

Recovery should retry bounded transient transport failures, reconcile stale state only after checking actual PID identity and ownership, and resume eligible disjoint work when another capability is unavailable. Quota exhaustion, missing dependencies, insufficient disk/memory and absent Lean pins require an explicit actionable status and retry boundary. Fault probes use owned fixture processes. They never kill an unrelated workload or remove shared caches. A planned task awaiting a real implementation is not a dead worker and must not trigger endless restart loops.

Preflight and explicit startup commands, from the JevOps root:

```bash
/home/barberb/lift_coding/external/ipfs_datasets/.venv/bin/python tools/check_lean_refactor_plan.py --check-all
/home/barberb/lift_coding/external/ipfs_datasets/.venv/bin/python tools/start_lean_refactor_supervisor.py
/home/barberb/lift_coding/external/ipfs_datasets/.venv/bin/python tools/start_lean_refactor_supervisor.py --start
```

Inspect fresh `data/lean_refactor_arena_20261024/startup.json`, lane status, guardian status and watchdog report, then actual task receipts. A spawned PID alone is insufficient. Startup acceptance requires observable task progress and at least one real Grok4.7 call through the strict router. A running server, a completed review or a green fixture suite must never be reported as a new Arena proof improvement.

## 9. Stop and promotion decisions

Stop a pilot on its declared deadline, model-call/verification cap, source drift, missing environment, failed ownership or memory guard. Preserve the verified incumbent and all rejected evidence. Increase a budget only through a reviewed, recorded configuration change. Do not train because inference has not yet been properly measured.

Promote methods in this order: exact native readiness; inexpensive deterministic shortening; frozen Leanstral feedback; retrieval/span ranking; then optional small adaptation. A method must improve a declared held-out metric at matched budgets and pass the original semantics/all-pin contract. Final outputs include an exact candidate portfolio, source/runtime/data manifests, cost ledger, negative results and reproducible report. External submission remains a later release decision.
