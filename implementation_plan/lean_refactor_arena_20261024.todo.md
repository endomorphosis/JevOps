# JevOps Lean Refactor Arena research taskboard — 2026-10-24

Consumable by ipfs_accelerate_py.agent_supervisor with task prefix `## JLR-`.

Objectives: `implementation_plan/lean_refactor_arena_20261024.objectives.md`
Machine graph: `implementation_plan/lean_refactor_arena_20261024.goals.json`
Profile: `config/lean_refactor_arena_20261024_supervisor.json`

Program decision: **IN_PROGRESS**. Bootstrap startup is not proof optimization or an official result.

## Execution contract

- All dependencies must complete before selection; planned research tickets remain nonselectable.
- One board owner and one model/GPU task at a time; ready writes must be disjoint.
- All bootstrap orchestration model calls use Grok4.7 through strict llm_router, without fallback. Planned Leanstral candidate generation has a separate explicit local route and native acceptance gate.
- Model outputs never write execution receipts, validators, this board, configuration or credentials.
- Real producer/validation outcomes authorize task completion; no existence-only scientific acceptance.
- Future capability waits are explicit and do not become synthetic proofs or training labels.

## JLR-001 Record current source, host, storage and compiler inventory

- Status: pending
- Priority: P0
- Track: planning
- Depends on:
- Goal id: JLR-G001
- Outputs: data/lean_refactor_campaign_20261024/JLR-001.inventory.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-001
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-001
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G001
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-001.inventory.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Actual current host and available tools are recorded with source identity; missing environments are explicitly unavailable, never verified.



Budget/stop rule: Stop at the task budget; record failures without inventing successful evidence.


Hypothesis: Current host capabilities can be measured without claiming historical proof environments still exist.

Measured fields: host identity, MemAvailable bytes, GPU allocated bytes, storage free bytes, actual Lean/Lake versions.

## JLR-002 Obtain the first strict Grok4.7 engineering review through llm_router

- Status: pending
- Priority: P0
- Track: planning
- Depends on: JLR-001
- Goal id: JLR-G001
- Inputs: implementation_plan/lean_refactor_arena_20261024.objectives.md, implementation_plan/lean_refactor_arena_20261024.bootstrap-context.md, data/lean_refactor_campaign_20261024/JLR-001.inventory.json
- Outputs: implementation_plan/proposals/JLR-002.review.json
- Deterministic command: python3 tools/run_lean_refactor_router_task.py --task-id JLR-002
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-002
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G001
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: grok-only
- Model: grok-4.7
- Implementation timeout seconds: 600
- Predicted files: implementation_plan/proposals/JLR-002.review.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Real strict provider/model receipt plus a bounded advisory JSON review; no fixture, hidden fallback or self-declared proof success.

Review the actual inventory and compact research context. Produce only three concise engineering risks, actions and acceptance boundaries in the supplied advisory JSON schema; entire response under3000characters. This startup review does not execute experiments or certify Lean proofs.

Budget/stop rule: Stop at the task budget; record failures without inventing successful evidence.


Hypothesis: Strict source-bound Grok4.7 reviews can be produced through llm_router without provider fallback.

Measured fields: exact effective provider/model, source-bound response receipt, advisory schema validity.

## JLR-003 Calibrate the existing offline evaluator protocol

- Status: pending
- Priority: P0
- Track: planning
- Depends on: JLR-001
- Goal id: JLR-G002
- Outputs: data/lean_refactor_campaign_20261024/JLR-003.calibration.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-003
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-003
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G002
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-003.calibration.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: The actual calibration command succeeds; fixture/calibration results remain explicitly non-official.



Budget/stop rule: Stop at the task budget; record failures without inventing successful evidence.


Hypothesis: The existing evaluator calibration protocol remains internally consistent on the current checkout.

Measured fields: actual calibration exit status, calibration fields, source receipt.

## JLR-004 Check frozen warm-up protocol without network or a model

- Status: pending
- Priority: P0
- Track: planning
- Depends on: JLR-001
- Goal id: JLR-G002
- Outputs: data/lean_refactor_campaign_20261024/JLR-004.offline-protocol.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-004
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-004
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G002
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-004.offline-protocol.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Offline self-check exercises healthy/down fixtures and retains rejected proofs; no fixture is labeled native.



Budget/stop rule: Stop at the task budget; record failures without inventing successful evidence.


Hypothesis: The frozen warmup protocol can be validated offline independently of inference or native proof claims.

Measured fields: actual offline self-check exit status, protocol checks.

## JLR-005 Inventory the exact local benchmark/version schedule

- Status: pending
- Priority: P0
- Track: planning
- Depends on: JLR-001
- Goal id: JLR-G003
- Outputs: data/lean_refactor_campaign_20261024/JLR-005.schedule.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-005
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-005
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G003
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-005.schedule.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Actual schedule and corpus digest are recorded; historical15/36 or current upstream counts are not silently substituted.



Budget/stop rule: Stop at the task budget; record failures without inventing successful evidence.


Hypothesis: The local historical benchmark exposes an auditable problem-by-version schedule distinct from the upcoming full release.

Measured fields: problem count, version count, pin schedule.

## JLR-006 Regression-check official-score arithmetic and missing-case treatment

- Status: pending
- Priority: P0
- Track: planning
- Depends on: JLR-003
- Goal id: JLR-G002
- Outputs: data/lean_refactor_campaign_20261024/JLR-006.scorer-parity.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-006
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-006
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G002
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-006.scorer-parity.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Known scorer fixtures match authoritative rounding, all-case denominators and missing-heartbeat treatment; tokenizer/worker parity remains separately unconfirmed.



Budget/stop rule: Stop at the task budget; record failures without inventing successful evidence.


Hypothesis: The local score arithmetic agrees with independently generated fixtures including missing and invalid cases.

Measured fields: independent scoring cases checked, rounding agreement, missing-case denominator.

## JLR-007 Implement a fail-closed proof-result policy filter

- Status: pending
- Priority: P0
- Track: planning
- Depends on: JLR-002
- Goal id: JLR-G002
- Inputs: implementation_plan/lean_refactor_arena_20261024.objectives.md, jevops/proof_trust.py
- Outputs: jevops/lra_safety_policy_v1.py
- Deterministic command: python3 tools/run_lean_refactor_router_task.py --task-id JLR-007
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-007
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G002
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: grok-only
- Model: grok-4.7
- Implementation timeout seconds: 600
- Predicted files: jevops/lra_safety_policy_v1.py
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Protected adversarial/random cases require exact statement/type/all-pin/axiom predicates and reject sorry/unsafe/malformed claims. This policy consumes trusted verifier results; it never verifies Lean itself.

Implement pure accept_candidate(row): row must be a dict; statement_preserved,type_preserved,all_pins_verified,axioms_subset must each be literal True; has_sorry,unsafe must each be literal False. Missing or malformed fields and non-dicts return False. Do not mutate inputs. This consumes trusted verifier summaries and never itself proves Lean. Pure module: functions/docstrings and allowed json/hashlib/math imports only; no module-level execution, decorators, default arguments, private attributes, dynamic imports or IO.

Budget/stop rule: Stop at the task budget; record failures without inventing successful evidence.


Hypothesis: Strict typed predicates can reject malformed or untrusted proof-result summaries before advisory selection.

Measured fields: strict Boolean and malformed-input cases, source-bound route receipt.

## JLR-008 Implement shortest-verified candidate selection

- Status: pending
- Priority: P0
- Track: planning
- Depends on: JLR-002
- Goal id: JLR-G002
- Inputs: implementation_plan/lean_refactor_arena_20261024.objectives.md, jevops/arena.py
- Outputs: jevops/lra_length_policy_v1.py
- Deterministic command: python3 tools/run_lean_refactor_router_task.py --task-id JLR-008
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-008
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G002
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: grok-only
- Model: grok-4.7
- Implementation timeout seconds: 600
- Predicted files: jevops/lra_length_policy_v1.py
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Protected cases choose min(tokens,heartbeats,id) among genuinely verified axiom-preserving candidates; invalid data fails closed. Official combined score is a separate report.

Implement pure select_candidate(rows)->id or None. Each admissible row is a dict with id:str, tokens:int>=1 excluding bool, heartbeats:int>=0 excluding bool, verified literal True and axioms_preserved literal True. Skip invalid rows. Choose minimum (tokens,heartbeats,id); empty/no admissible rows return None. Do not mutate inputs. This selects already independently verified candidates only. Pure module: functions/docstrings and allowed json/hashlib/math imports only; no module-level execution, decorators, default arguments, private attributes, dynamic imports or IO.

Budget/stop rule: Stop at the task budget; record failures without inventing successful evidence.


Hypothesis: Length-first selection can deterministically choose only already-verified, axiom-preserving candidates.

Measured fields: length-first selection cases, invalid-row rejection, tie-break determinism.

## JLR-009 Implement environment-complete source cache identities

- Status: pending
- Priority: P0
- Track: planning
- Depends on: JLR-002
- Goal id: JLR-G002
- Inputs: implementation_plan/lean_refactor_arena_20261024.objectives.md
- Outputs: jevops/lra_cache_identity_v1.py
- Deterministic command: python3 tools/run_lean_refactor_router_task.py --task-id JLR-009
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-009
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G002
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: grok-only
- Model: grok-4.7
- Implementation timeout seconds: 600
- Predicted files: jevops/lra_cache_identity_v1.py
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Protected randomized tests show source and every context dimension change the SHA256 cache identity; no source normalization erases meaningful bytes.

Implement pure cache_key(context,source)->SHA256 hex digest of canonical UTF8 JSON {'context':context,'source':source}, ensure_ascii=False, sort_keys=True,separators=(',',':'). Preserve exact source bytes and every context dimension. Do not mutate either input. Pure module: functions/docstrings and allowed json/hashlib/math imports only; no module-level execution, decorators, default arguments, private attributes, dynamic imports or IO.

Budget/stop rule: Stop at the task budget; record failures without inventing successful evidence.


Hypothesis: Exact source plus complete environmental context avoids false cache reuse after any pin or source mutation.

Measured fields: canonical digest parity, source and environment mutation sensitivity.

## JLR-010 Run an actual Lean4.31 kernel smoke on a non-Arena theorem

- Status: pending
- Priority: P0
- Track: planning
- Depends on: JLR-004, JLR-007
- Goal id: JLR-G002
- Outputs: data/lean_refactor_campaign_20261024/JLR-010.native-smoke.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-010
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-010
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G002
- Parallel lane: jlr-planning
- Resource class: cpu-lean
- Provider role: deterministic
- Implementation timeout seconds: 900
- Predicted files: data/lean_refactor_campaign_20261024/JLR-010.native-smoke.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Actual pinned Lean execution verifies baseline and candidate, exact target and transitive axioms; report explicitly states non-Arena and no official score.



Budget/stop rule: Stop at the task budget; record failures without inventing successful evidence.


Hypothesis: The available Lean4.31 toolchain can independently check an actual non-Arena theorem and candidate.

Measured fields: actual compiler identity, reference and candidate VERIFIED/MEASURED, type and axiom preservation, raw heartbeats.

## JLR-011 Design the version-aware retrieval and strategy ablation

- Status: pending
- Priority: P1
- Track: planning
- Depends on: JLR-005, JLR-008, JLR-009
- Goal id: JLR-G004
- Inputs: implementation_plan/lean_refactor_arena_20261024.objectives.md, implementation_plan/lean_refactor_arena_20261024.research.md, data/lean_refactor_campaign_20261024/JLR-005.schedule.json
- Outputs: implementation_plan/proposals/JLR-011.review.json
- Deterministic command: python3 tools/run_lean_refactor_router_task.py --task-id JLR-011
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-011
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G004
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: grok-only
- Model: grok-4.7
- Implementation timeout seconds: 600
- Predicted files: implementation_plan/proposals/JLR-011.review.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Real Grok router receipt and schema-valid advisory review with concrete risks/actions/acceptance boundaries. This task completes a design artifact, not the proposed implementation or an experiment.

Specify lexical, typed-head and version-filtered controls at equal compiler budgets; use prior neutral typed-premise/depth results and do not repeat them as new wins.

Budget/stop rule: Stop at the task budget; record failures without inventing successful evidence.


Hypothesis: Version-aware retrieval may improve useful suggestions beyond the prior neutral typed-premise pilot.

Measured fields: matched compiler budget, proposed ablations, prior neutral control acknowledged.

## JLR-012 Design the verified span/autoencoder data adapter

- Status: pending
- Priority: P1
- Track: planning
- Depends on: JLR-002, JLR-009
- Goal id: JLR-G006
- Inputs: implementation_plan/lean_refactor_arena_20261024.objectives.md, implementation_plan/lean_refactor_arena_20261024.research.md
- Outputs: implementation_plan/proposals/JLR-012.review.json
- Deterministic command: python3 tools/run_lean_refactor_router_task.py --task-id JLR-012
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-012
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G006
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: grok-only
- Model: grok-4.7
- Implementation timeout seconds: 600
- Predicted files: implementation_plan/proposals/JLR-012.review.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Real Grok router receipt and schema-valid advisory review with concrete risks/actions/acceptance boundaries. This task completes a design artifact, not the proposed implementation or an experiment.

Map Lean parser/goal/source/pin records to existing CPU sparse encoder and Datasets source-custody interfaces; exclude environment failures and frozen holdout data from training.

Budget/stop rule: Stop at the task budget; record failures without inventing successful evidence.


Hypothesis: Existing span provenance and lightweight encoder interfaces can transfer to Lean with explicit binder and project identities.

Measured fields: provenance dimensions, group split boundaries, environment-failure exclusion.

## JLR-013 Design bounded Leanstral context and iterative repair experiments

- Status: pending
- Priority: P1
- Track: planning
- Depends on: JLR-002, JLR-007
- Goal id: JLR-G005
- Inputs: implementation_plan/lean_refactor_arena_20261024.objectives.md, implementation_plan/lean_refactor_arena_20261024.research.md
- Outputs: implementation_plan/proposals/JLR-013.review.json
- Deterministic command: python3 tools/run_lean_refactor_router_task.py --task-id JLR-013
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-013
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G005
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: grok-only
- Model: grok-4.7
- Implementation timeout seconds: 600
- Predicted files: implementation_plan/proposals/JLR-013.review.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Real Grok router receipt and schema-valid advisory review with concrete risks/actions/acceptance boundaries. This task completes a design artifact, not the proposed implementation or an experiment.

Use the verified community Q4 artifact and actual localhost endpoint only after resource readiness; compare original-proof, goal-state and retrieved-context prompts, with explicit rfl protocol smoke separate from proof improvement.

Budget/stop rule: Stop at the task budget; record failures without inventing successful evidence.


Hypothesis: Bounded compiler-feedback prompts can be evaluated with frozen quantized Leanstral before any training.

Measured fields: context tokens, inference deadline, native-verifier boundary.

## JLR-014 Design the limited-compute training decision

- Status: pending
- Priority: P1
- Track: planning
- Depends on: JLR-002, JLR-012
- Goal id: JLR-G007
- Inputs: implementation_plan/lean_refactor_arena_20261024.objectives.md, implementation_plan/lean_refactor_arena_20261024.research.md, implementation_plan/proposals/JLR-012.review.json
- Outputs: implementation_plan/proposals/JLR-014.review.json
- Deterministic command: python3 tools/run_lean_refactor_router_task.py --task-id JLR-014
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-014
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G007
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: grok-only
- Model: grok-4.7
- Implementation timeout seconds: 600
- Predicted files: implementation_plan/proposals/JLR-014.review.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Real Grok router receipt and schema-valid advisory review with concrete risks/actions/acceptance boundaries. This task completes a design artifact, not the proposed implementation or an experiment.

Do not full-finetune119B. Specify matched CPU-encoder/lexical baselines and a later small-model LoRA memory/holdout gate; inference GGUF is not automatically a trainable checkpoint.

Budget/stop rule: Stop at the task budget; record failures without inventing successful evidence.


Hypothesis: Measured frozen-model and CPU-encoder results can justify or reject later small-model adaptation.

Measured fields: measured memory prerequisite, holdout gate, no full119B training.

## JLR-015 Review supervisor recovery and campaign activation criteria

- Status: pending
- Priority: P1
- Track: planning
- Depends on: JLR-002, JLR-010
- Goal id: JLR-G008
- Inputs: implementation_plan/lean_refactor_arena_20261024.objectives.md, implementation_plan/lean_refactor_arena_20261024.research.md
- Outputs: implementation_plan/proposals/JLR-015.review.json
- Deterministic command: python3 tools/run_lean_refactor_router_task.py --task-id JLR-015
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-015
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G008
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: grok-only
- Model: grok-4.7
- Implementation timeout seconds: 600
- Predicted files: implementation_plan/proposals/JLR-015.review.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Real Grok router receipt and schema-valid advisory review with concrete risks/actions/acceptance boundaries. This task completes a design artifact, not the proposed implementation or an experiment.

Enumerate bounded failure probes for provider timeout/quota, malformed JSON, changed output inode, missing native environment, occupiedGPU, disk pressure and dead owner; define observable recovery and honest planned-backlog activation.

Budget/stop rule: Stop at the task budget; record failures without inventing successful evidence.


Hypothesis: Explicit failure bounds and owned-process recovery can prevent silent waiting and false task completion.

Measured fields: bounded attempts, observable failure reason, owned recovery, honest backlog activation.

## JLR-016 Provision exact-pin projects and repair ArkLib/Putnam readiness

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-005, JLR-010, JLR-015
- Goal id: JLR-G003
- Outputs: data/lean_refactor_campaign_20261024/JLR-016.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-016
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-016
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G003
- Parallel lane: jlr-planning
- Resource class: cpu-lean
- Provider role: deterministic
- Implementation timeout seconds: 900
- Predicted files: data/lean_refactor_campaign_20261024/JLR-016.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Every corpus/version pair has explicit current-ready or actionable unavailable state; native failures are not negative training examples.

Create a NEW capped owned project root; fetch exact commits/toolchains; repair source-location and import mismatches without overwriting historical caches.

Budget/stop rule: Perproject exact Lean/Lake/dependency manifest, source-prefix and target-location audit; <=8GiB pilot storage and <=2 compiler processes.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Provision exact-pin projects and repair ArkLib/Putnam readiness.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-017 Recheck all reference proofs and retained incumbents

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-016
- Goal id: JLR-G003
- Outputs: data/lean_refactor_campaign_20261024/JLR-017.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-017
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-017
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G003
- Parallel lane: jlr-planning
- Resource class: cpu-lean
- Provider role: deterministic
- Implementation timeout seconds: 900
- Predicted files: data/lean_refactor_campaign_20261024/JLR-017.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Fresh all-pin target/type/axiom receipts; retain baseline for failed/unavailable cases and never zero-fill missing checks as success.

Use the existing NativeLeanVerifier and project bindings; original and incumbent on every required pin.

Budget/stop rule: <=36 initial launches;60s each; one compiler at a time; complete matrix or explicit partial status.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Recheck all reference proofs and retained incumbents.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-018 Establish tokenizer and heartbeat worker parity

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-006, JLR-017
- Goal id: JLR-G002
- Outputs: data/lean_refactor_campaign_20261024/JLR-018.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-018
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-018
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G002
- Parallel lane: jlr-planning
- Resource class: cpu-lean
- Provider role: deterministic
- Implementation timeout seconds: 900
- Predicted files: data/lean_refactor_campaign_20261024/JLR-018.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Report parity proven only for available worker interfaces; distinguish local tokenizer, raw heartbeats and official metrics.

Compare the exact scorer/tokenizer/reference denominators and pinned measurement options against the organizer specification.

Budget/stop rule: Balanced ABBA ordering; matched cold/warm cache labels; at least3 paired repeats for finalists.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Establish tokenizer and heartbeat worker parity.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-019 Implement profile-guided simplifier support minimization

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-011, JLR-017
- Goal id: JLR-G004
- Outputs: data/lean_refactor_campaign_20261024/JLR-019.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-019
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-019
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G004
- Parallel lane: jlr-planning
- Resource class: cpu-lean
- Provider role: deterministic
- Implementation timeout seconds: 900
- Predicted files: data/lean_refactor_campaign_20261024/JLR-019.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Actual shorter all-pin-valid body beats freshly rechecked incumbent; no axiom growth or unpaid helper declarations.

Reuse existing support/simp-scope/deletion tools; rank expensive spans and minimize simp only support with complete-source replay.

Budget/stop rule: Matched deterministic controls, capped12 candidates and24 verification launches per pilot.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Implement profile-guided simplifier support minimization.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-020 Implement coupled deletion and induction-context repair

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-011, JLR-017
- Goal id: JLR-G004
- Outputs: data/lean_refactor_campaign_20261024/JLR-020.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-020
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-020
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G004
- Parallel lane: jlr-planning
- Resource class: cpu-lean
- Provider role: deterministic
- Implementation timeout seconds: 900
- Predicted files: data/lean_refactor_campaign_20261024/JLR-020.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Whole theorem survives all pins and exact target; count all coupled edits and final proof source.

Generalize the known Hlen2 plus IH/goal-block repair, tracking binder dependencies and source spans rather than isolated line deletion.

Budget/stop rule: Compare isolated deletion versus coupled repair under identical verification budgets.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Implement coupled deletion and induction-context repair.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-021 Implement search-then-extract explicit proof terms

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-017, JLR-019
- Goal id: JLR-G004
- Outputs: data/lean_refactor_campaign_20261024/JLR-021.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-021
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-021
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G004
- Parallel lane: jlr-planning
- Resource class: cpu-lean
- Provider role: deterministic
- Implementation timeout seconds: 900
- Predicted files: data/lean_refactor_campaign_20261024/JLR-021.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Final emitted proof is independently cold-replayed with export growth bounds; discovery script length is not final length.

Allow bounded discovery scripts to be longer, then extract/specialize simp?/aesop?/grind? or explicit terms supported by the actual pin.

Budget/stop rule: Original/native tactics only; no importing unavailable Mathlib into Core; <=12 search branches.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Implement search-then-extract explicit proof terms.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-022 Run a fixed-winner deterministic portfolio comparison

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-018, JLR-019, JLR-020, JLR-021
- Goal id: JLR-G004
- Outputs: data/lean_refactor_campaign_20261024/JLR-022.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-022
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-022
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G004
- Parallel lane: jlr-planning
- Resource class: cpu-lean
- Provider role: deterministic
- Implementation timeout seconds: 900
- Predicted files: data/lean_refactor_campaign_20261024/JLR-022.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: All-pin correctness, shortest-verified frontier and separately strict-dual/official-score arms; never global-shortest claims.

Freeze winners before a fresh confirmation run; include original and incumbent controls.

Budget/stop rule: Report failed/unavailable cases in whole-corpus denominator and seed/order noise.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Run a fixed-winner deterministic portfolio comparison.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-023 Qualify downloaded Leanstral weights, runtime and resource ownership

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-013, JLR-015
- Goal id: JLR-G005
- Outputs: data/lean_refactor_campaign_20261024/JLR-023.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-023
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-023
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G005
- Parallel lane: jlr-planning
- Resource class: gpu-inference
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-023.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Real /health/models plus16-token inference; aliases not proof of official checkpoint ancestry; no old server takeover.

Verify full artifactSHA, architecture/chat template, CUDA runtime and exactlocalhost model descriptor; acquire only owned GPU resources.

Budget/stop rule: Q4~67.2GiB disk; partial18-layer offload across2x3090; ctx2048;<=20GiB/card, RSS48GiB, hostavailable>=16GiB.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Qualify downloaded Leanstral weights, runtime and resource ownership.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-024 Run bounded frozen-Leanstral iterative shortening

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-017, JLR-018, JLR-023
- Goal id: JLR-G005
- Outputs: data/lean_refactor_campaign_20261024/JLR-024.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-024
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-024
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G005
- Parallel lane: jlr-planning
- Resource class: gpu-inference
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-024.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: All-pin Lean acceptance and original-source replacement required; response text and model confidence have zero proof authority.

Feed exact source/goal context and actual compiler diagnostics into a bounded edit loop with an unchanged verified incumbent.

Budget/stop rule: Start2 requests,<=1024 input/256 outputtokens,90s each,<=240s total; record every failed call.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Run bounded frozen-Leanstral iterative shortening.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-025 Ablate prompt context and retrieval independently

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-011, JLR-024
- Goal id: JLR-G005
- Outputs: data/lean_refactor_campaign_20261024/JLR-025.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-025
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-025
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G005
- Parallel lane: jlr-planning
- Resource class: gpu-inference
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-025.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Matched calls/tokens/verification launches, held-fixed source families, actual verified shortest candidates.

Compare source-only, goal-state, version-aware strategy and typed-premise contexts, avoiding already-neutral depth-only rediscovery.

Budget/stop rule: Freeze protocol and seeds before evaluating; keep all negative outcomes.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Ablate prompt context and retrieval independently.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-026 Implement Lean-specific span provenance adapter

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-012, JLR-017
- Goal id: JLR-G006
- Outputs: data/lean_refactor_campaign_20261024/JLR-026.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-026
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-026
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G006
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-026.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Original source reconstructs exactly; stale spans/cross-version entries are rejected; legal-domain weights are never relabeled as Lean proof models.

Adapt Datasets span/cache identity and GTE reuse metadata to Lean binders, dependency graph, source ranges and exact project pins.

Budget/stop rule: Use cached embeddings when authenticated; any native model load separately budgeted.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Implement Lean-specific span provenance adapter.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-027 Create group-disjoint verified edit training records

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-022, JLR-024, JLR-026
- Goal id: JLR-G006
- Outputs: data/lean_refactor_campaign_20261024/JLR-027.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-027
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-027
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G006
- Parallel lane: jlr-planning
- Resource class: cpu-lean
- Provider role: deterministic
- Implementation timeout seconds: 900
- Predicted files: data/lean_refactor_campaign_20261024/JLR-027.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Split by project/theorem/alias/dependency family before training; no canary or holdout exposure; exclude infrastructure failures from semantic labels.

Collect only genuinely verified original/candidate edit pairs and compiler classifications.

Budget/stop rule: Bounded corpus size and reproducible manifest seeds; public warmup is development data.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Create group-disjoint verified edit training records.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-028 Run CPU sparse-autoencoder and lexical matched controls

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-027
- Goal id: JLR-G006
- Outputs: data/lean_refactor_campaign_20261024/JLR-028.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-028
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-028
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G006
- Parallel lane: jlr-planning
- Resource class: cpu-lean
- Provider role: deterministic
- Implementation timeout seconds: 900
- Predicted files: data/lean_refactor_campaign_20261024/JLR-028.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Frozen holdout verified gain per compiler call/CPUminute exceeds lexical control; CE/cosine/reconstruction losses alone cannot promote.

Reuse JevOps256-feature/latent16 sparse trainer, operation loss and actual prediction accounting.

Budget/stop rule: 2arms x32updates, batch8,input512tokens,2CPUthreads,RSS4GiB,600s/arm.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Run CPU sparse-autoencoder and lexical matched controls.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-029 Evaluate parser-bound span infilling or edit ranking

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-028
- Goal id: JLR-G006
- Outputs: data/lean_refactor_campaign_20261024/JLR-029.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-029
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-029
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G006
- Parallel lane: jlr-planning
- Resource class: cpu-lean
- Provider role: deterministic
- Implementation timeout seconds: 900
- Predicted files: data/lean_refactor_campaign_20261024/JLR-029.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Actual decoded predictions cold-verify; never substitute a search-selected teacher for model performance.

Use BART/T5-style masking as an experimental objective, preserving binders and original-source offsets; compare rank-only and reconstruction paths.

Budget/stop rule: No large transformer training by default; equal compiler budgets to CPU ranker.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Evaluate parser-bound span infilling or edit ranking.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-030 Decide whether any small-model LoRA is justified

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-014, JLR-025, JLR-028, JLR-029
- Goal id: JLR-G007
- Outputs: data/lean_refactor_campaign_20261024/JLR-030.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-030
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-030
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G007
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-030.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Continue frozen inference unless validated improvement clears baseline with unchanged correctness and memory guardrails.

Use measured failure modes and gain per compute to decide inference-only versus a small adaptation.

Budget/stop rule: Full119B FT disabled; no direct GGUF-to-QLoRA assumption.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Decide whether any small-model LoRA is justified.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-031 Optionally run a small compatible adapter memory smoke

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-030
- Goal id: JLR-G007
- Outputs: data/lean_refactor_campaign_20261024/JLR-031.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-031
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-031
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G007
- Parallel lane: jlr-planning
- Resource class: gpu-small
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-031.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: 10actualsteps stay<=16GiB onONE3090 and preserve host headroom; otherwise stop and retain inference-only strategy.

Only if explicitly enabled, use a licensed compatible1–3B base already provisioned and framework-supported.

Budget/stop rule: LoRA r8/alpha16/dropout.05;seq512;batch1/accum8;<=300s smoke; no119B fullFT.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Optionally run a small compatible adapter memory smoke.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-032 Optionally test a frozen adapted proposer on held-out families

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-031
- Goal id: JLR-G007
- Outputs: data/lean_refactor_campaign_20261024/JLR-032.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-032
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-032
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G007
- Parallel lane: jlr-planning
- Resource class: gpu-small
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-032.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Measured all-pin verified improvement over frozen and retrieval-only controls; no promotion from training loss or selected benchmark examples.

At most100steps/1800s pilot after memory smoke; freeze checkpoint before one held-out evaluation.

Budget/stop rule: One adapter arm; preserve unmodified base and rollback descriptor.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Optionally test a frozen adapted proposer on held-out families.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-033 Fault-test the running supervisor without corrupting proofs

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-015, JLR-022
- Goal id: JLR-G008
- Outputs: data/lean_refactor_campaign_20261024/JLR-033.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-033
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-033
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G008
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-033.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Real bounded recovery or explicit triaged blocker; only changed evidence rearms gates; no fabricated heartbeat/completion.

Use owned fixture jobs for timeout/quota, output CAS, source drift, lost resource lease, disk pressure and dead process.

Budget/stop rule: 3attempts,15min cooldown, source-aware gate limits; never kill unrelated PIDs.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Fault-test the running supervisor without corrupting proofs.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-034 Activate measured campaign stages from verified prerequisites

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-017, JLR-018, JLR-023, JLR-033
- Goal id: JLR-G008
- Outputs: data/lean_refactor_campaign_20261024/JLR-034.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-034
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-034
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G008
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-034.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Unknown action/argv remains nonselectable planned backlog; no file-existence-only feature completion; preserve task history.

Materialize exact reviewed producer argv/protected validators for planned research tickets only when their capability gates are satisfied.

Budget/stop rule: One owner, one GPU job and bounded model calls; source-bound activation receipt.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Activate measured campaign stages from verified prerequisites.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-035 Refresh full benchmark inventory at release

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-017
- Goal id: JLR-G009
- Outputs: data/lean_refactor_campaign_20261024/JLR-035.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-035
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-035
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G009
- Parallel lane: jlr-planning
- Resource class: cpu-lean
- Provider role: deterministic
- Implementation timeout seconds: 900
- Predicted files: data/lean_refactor_campaign_20261024/JLR-035.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: No unreleased/full benchmark claims; exact corpus/version digest and complete denominators.

Read official release metadata on/after November1 and add new cases as a new pinned cohort; preserve old15-case history.

Budget/stop rule: Small metadata requests; no submission or model calls as side effects.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Refresh full benchmark inventory at release.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-036 Run full budget-accounted final evaluation

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-022, JLR-024, JLR-034, JLR-035
- Goal id: JLR-G009
- Outputs: data/lean_refactor_campaign_20261024/JLR-036.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-036
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-036
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G009
- Parallel lane: jlr-planning
- Resource class: cpu-lean
- Provider role: deterministic
- Implementation timeout seconds: 900
- Predicted files: data/lean_refactor_campaign_20261024/JLR-036.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: Hard correctness contract plus official score with exact rounding/denominators and all missing cases; local proxies separately named.

Recheck fixed candidates on every required version; retain original fallback; evaluate training arms only if legitimately qualified.

Budget/stop rule: Closed track all model calls via OpenRouter<=US$3/problem; open track public weights and reproducible<=4x80GB A100/48h inference.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Run full budget-accounted final evaluation.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-037 Prepare reproducible portfolio and technical report

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-036
- Goal id: JLR-G009
- Outputs: data/lean_refactor_campaign_20261024/JLR-037.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-037
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-037
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G009
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-037.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: All source inside charged proof body; no extra axioms/unpaid helper pollution; all necessary licenses and actual measurements recorded.

Bundle exact proofs, source/weights/config manifests, rejection history and reproduction commands with per-problem budgets.

Budget/stop rule: Report Approach/Models/Budget accounting/Reproduction sections,3–9pages if current rules unchanged.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Prepare reproducible portfolio and technical report.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.

## JLR-038 Review submission eligibility and external publication

- Status: planned
- Priority: P2
- Track: research
- Depends on: JLR-037
- Goal id: JLR-G009
- Outputs: data/lean_refactor_campaign_20261024/JLR-038.result.json
- Deterministic command: python3 tools/run_lean_refactor_campaign.py --task-id JLR-038
- Validation: python3 tools/check_lean_refactor_plan.py --validate-task JLR-038
- Board namespace: jevops-lean-refactor-20261024
- Bundle: jevops/lean-refactor/JLR-G009
- Parallel lane: jlr-planning
- Resource class: cpu-small
- Provider role: deterministic
- Implementation timeout seconds: 600
- Predicted files: data/lean_refactor_campaign_20261024/JLR-038.result.json
- Conflict policy: Own only declared outputs; do not change trusted validators, task history, credentials or unrelated jobs.
- Acceptance: No autonomous account claims, competition submissions or external messages from this development startup; obtain separate release instruction.

Review organizer rules again and prepare the final upload as an explicit release candidate.

Budget/stop rule: Preserve untouched proof portfolio and audit trail.


Hypothesis: A bounded, controlled implementation of this work package can satisfy its stated acceptance criteria and improve the evidence needed for the parent goal: Review submission eligibility and external publication.

Measured fields: verified token count, raw heartbeats by exact pin, compatibility across required pins, verified candidate rate, model calls and token usage, wall time and peak memory.
