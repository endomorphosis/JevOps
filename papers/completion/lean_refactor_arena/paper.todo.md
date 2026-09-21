# Lean Refactor Arena — implementation taskboard

Read `papers/completion/lean_refactor_arena/review.md` and `papers/completion/lean_refactor_arena/design_win_plan.md` before work.
Objective heap: `papers/completion/lean_refactor_arena/paper.objectives.md`. Board namespace: `vericodegen-2026-lean_refactor_arena`.

Primary path: Leanstral on live docker0 (`172.17.0.1:8080`) + in-repo `harness/run_warmup.py`.
Never invent Arena scores. Spark NVFP4 is not official Track 2. Jev does not generate Lean.
Implement in native ephemeral worktrees. GPU tasks are exclusive clients of docker0; do not LOCK_EX.
Each task writes its receipt using the contract in the runbook.

## LRA-010 Thin fail-closed Leanstral generate_text entry point

- Status: todo
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: lean_refactor_arena
- Depends on:
- Goal id: LRA-S01
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S01
- Parallel lane: lra-cpu-a
- Outputs: papers/completion/lean_refactor_arena/harness/generate_text.py, papers/completion/lean_refactor_arena/harness/lra_prompt.txt, papers/completion/lean_refactor_arena/receipts/LRA-010.json
- Predicted files: papers/completion/lean_refactor_arena/harness/generate_text.py, papers/completion/lean_refactor_arena/harness/lra_prompt.txt, papers/completion/lean_refactor_arena/receipts/LRA-010.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-010/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/, external/ipfs_accelerate/ipfs_accelerate_py/
- Resource class: cpu-medium
- Resource stage: execution
- Implementation timeout seconds: 7200
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-010
- Acceptance: generate_text uses provider=leanstral_local, model_name=Leanstral, temperature=0.0, allow_local_fallback=False, allow_cross_provider_fallback=False, disable_model_retry=True.; Unreachable docker0 fails closed without Grok/HF fallback; receipts record resolved provider/model.; No LOCK_EX; no second llama-server; no compile; no Arena scores.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-010.json

Implement papers/completion/lean_refactor_arena/harness/generate_text.py as an HTTP client of 172.17.0.1:8080. Probe /health. Call ipfs_accelerate_py.llm_router.generate_text with fail-closed kwargs. Do not import LeanstralProofProvider. Do not start llama-server. Do not claim scores.

Acceptance criteria:

1. generate_text uses provider=leanstral_local, model_name=Leanstral, temperature=0.0, allow_local_fallback=False, allow_cross_provider_fallback=False, disable_model_retry=True.
2. Unreachable docker0 fails closed without Grok/HF fallback; receipts record resolved provider/model.
3. No LOCK_EX; no second llama-server; no compile; no Arena scores.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-011 Prefix splice tests on all 15 warm-up records

- Status: todo
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: lean_refactor_arena
- Depends on:
- Goal id: LRA-S02
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S02
- Parallel lane: lra-cpu-b
- Outputs: papers/completion/lean_refactor_arena/harness/splice.py, papers/completion/lean_refactor_arena/harness/test_splice.py, papers/completion/lean_refactor_arena/receipts/LRA-011.json
- Predicted files: papers/completion/lean_refactor_arena/harness/splice.py, papers/completion/lean_refactor_arena/harness/test_splice.py, papers/completion/lean_refactor_arena/receipts/LRA-011.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-011/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/
- Resource class: cpu-medium
- Resource stage: execution
- Implementation timeout seconds: 3600
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-011
- Acceptance: Every warm-up record satisfies src.startswith(statement); body is the suffix after the statement.; Never scan for the first :=; named := inside types remains part of the frozen statement.; Unit test covers all 15 records; SHA-256 of the JSONL remains 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-011.json

JSONL splice is src.startswith(statement). ArkLib/CSLib statements contain := in types. Write harness/splice.py and a unit test over data/benchmark_data_warmup.jsonl. Lexical admission uses statement + ' := by\nsorry' plus tactic-only proof_text.

Acceptance criteria:

1. Every warm-up record satisfies src.startswith(statement); body is the suffix after the statement.
2. Never scan for the first :=; named := inside types remains part of the frozen statement.
3. Unit test covers all 15 records; SHA-256 of the JSONL remains 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-012 Tag-pinned Lean/lake toolchain resolver

- Status: todo
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: lean_refactor_arena
- Depends on:
- Goal id: LRA-S03
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S03
- Parallel lane: lra-cpu-c
- Outputs: external/ipfs_datasets/ipfs_datasets_py/logic/hammers/frontends/lean_toolchain.py, papers/completion/lean_refactor_arena/receipts/LRA-012.json
- Predicted files: external/ipfs_datasets/ipfs_datasets_py/logic/hammers/frontends/lean_toolchain.py, papers/completion/lean_refactor_arena/receipts/LRA-012.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-012/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/, external/ipfs_datasets/ipfs_datasets_py/logic/hammers/
- Resource class: cpu-medium
- Resource stage: execution
- Implementation timeout seconds: 3600
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-012
- Acceptance: Resolver returns tag-pinned elan lean and lake paths from JSONL version_info.; EnvironmentLockRecord is populated via executable_paths, not primary_executable.; LeanFrontend PATH lean --json behavior is unchanged.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-012.json

Add lean_toolchain.py next to hammers/frontends/lean.py. Compile worker will use run_lean_process. Do not make LeanFrontend.snapshot_goal lake-aware in this task.

Acceptance criteria:

1. Resolver returns tag-pinned elan lean and lake paths from JSONL version_info.
2. EnvironmentLockRecord is populated via executable_paths, not primary_executable.
3. LeanFrontend PATH lean --json behavior is unchanged.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-013 Bake lake oleans and Putnam Mathlib lake projects

- Status: todo
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: lean_refactor_arena
- Depends on: LRA-012
- Goal id: LRA-S03
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S03
- Parallel lane: lra-cpu-c
- Outputs: papers/completion/lean_refactor_arena/harness/putnam_lake/README.md, papers/completion/lean_refactor_arena/harness/bake_oleans.py, papers/completion/lean_refactor_arena/receipts/LRA-013.json
- Predicted files: papers/completion/lean_refactor_arena/harness/putnam_lake/README.md, papers/completion/lean_refactor_arena/harness/bake_oleans.py, papers/completion/lean_refactor_arena/receipts/LRA-013.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-013/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/
- Resource class: cpu-heavy
- Resource stage: execution
- Implementation timeout seconds: 7200
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-013
- Acceptance: Strata v4.26 olean bake is recorded first; missing cache fails closed under network=deny.; Putnam is a per-tag Mathlib+Aesop lake project, not Tmp.lean.; No Arena scores.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-013.json

First lake build is hours. Bake oleans before the 48h clock. Putnam records have empty url/file_path and import Mathlib/Aesop.

Acceptance criteria:

1. Strata v4.26 olean bake is recorded first; missing cache fails closed under network=deny.
2. Putnam is a per-tag Mathlib+Aesop lake project, not Tmp.lean.
3. No Arena scores.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-014 Multi-tag lake compile worker starting with one Strata file

- Status: todo
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: lean_refactor_arena
- Depends on: LRA-011, LRA-012, LRA-013
- Goal id: LRA-S03
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S03
- Parallel lane: lra-cpu-c
- Outputs: papers/completion/lean_refactor_arena/harness/compile_worker.py, papers/completion/lean_refactor_arena/receipts/LRA-014.json
- Predicted files: papers/completion/lean_refactor_arena/harness/compile_worker.py, papers/completion/lean_refactor_arena/receipts/LRA-014.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-014/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/
- Resource class: cpu-heavy
- Resource stage: execution
- Implementation timeout seconds: 7200
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-014
- Acceptance: One Strata module compiles via lake env lean with finite measurement maxHeartbeats.; Per-tag timeout and axiom-digest receipts are written.; IndependentKernelVerifier 30s default is not the lake oracle.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-014.json

Cached clone, checkout commit, lake env lean. Measurement command forces finite maxHeartbeats even if Putnam headers zero it. Expand tags after one file is green.

Acceptance criteria:

1. One Strata module compiles via lake env lean with finite measurement maxHeartbeats.
2. Per-tag timeout and axiom-digest receipts are written.
3. IndependentKernelVerifier 30s default is not the lake oracle.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-015 Dedicated verify_lra_batch fail-closed verifier

- Status: todo
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: lean_refactor_arena
- Depends on: LRA-014
- Goal id: LRA-S03
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S03
- Parallel lane: lra-cpu-b
- Outputs: papers/completion/lean_refactor_arena/tools/verify_lra_batch.py, papers/completion/lean_refactor_arena/receipts/LRA-015.json
- Predicted files: papers/completion/lean_refactor_arena/tools/verify_lra_batch.py, papers/completion/lean_refactor_arena/receipts/LRA-015.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-015/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/
- Resource class: cpu-medium
- Resource stage: execution
- Implementation timeout seconds: 3600
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-015
- Acceptance: Verifier requires digest, statement-bind, all listed tags, no sorryAx, one receipt per scheduled problem.; Does not import law_to_action verify_batch.py.; Does not write Arena scores.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-015.json

Copy the fail-closed pattern from law_to_action verify_batch without sharing that missing path. --require-complete.

Acceptance criteria:

1. Verifier requires digest, statement-bind, all listed tags, no sorryAx, one receipt per scheduled problem.
2. Does not import law_to_action verify_batch.py.
3. Does not write Arena scores.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-016 Docker0 HTTP client; never owner LOCK_EX

- Status: todo
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: lean_refactor_arena
- Depends on: LRA-010
- Goal id: LRA-S01
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S01
- Parallel lane: lra-cpu-a
- Outputs: papers/completion/lean_refactor_arena/harness/docker0_client.py, papers/completion/lean_refactor_arena/receipts/LRA-016.json
- Predicted files: papers/completion/lean_refactor_arena/harness/docker0_client.py, papers/completion/lean_refactor_arena/receipts/LRA-016.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-016/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/, external/ipfs_accelerate/ipfs_accelerate_py/
- Resource class: cpu-medium
- Resource stage: execution
- Implementation timeout seconds: 3600
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-016
- Acceptance: Probe http://172.17.0.1:8080/health; if healthy, generate_text as client without LOCK_EX.; IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART=0; never start a second llama-server.; If unhealthy and gpu-0.lock free, may exec run_leanstral_ephemeral.py --bind docker0 --gpu 0; if EX held, wait or skip LLM.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-016.json

gpu-0.lock is the owner lock held by law_to_action / run_leanstral_ephemeral.py. LRA is a client of the live server.

Acceptance criteria:

1. Probe http://172.17.0.1:8080/health; if healthy, generate_text as client without LOCK_EX.
2. IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART=0; never start a second llama-server.
3. If unhealthy and gpu-0.lock free, may exec run_leanstral_ephemeral.py --bind docker0 --gpu 0; if EX held, wait or skip LLM.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-017 run_warmup.py loop v1 using Leanstral on this machine

- Status: todo
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: lean_refactor_arena
- Depends on: LRA-014, LRA-016
- Goal id: LRA-S04
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S04
- Parallel lane: lra-gpu
- Outputs: papers/completion/lean_refactor_arena/harness/run_warmup.py, papers/completion/lean_refactor_arena/receipts/LRA-017.json
- Predicted files: papers/completion/lean_refactor_arena/harness/run_warmup.py, papers/completion/lean_refactor_arena/receipts/LRA-017.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-017/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/
- Resource class: gpu-leanstral
- Resource stage: execution
- Implementation timeout seconds: 7200
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-017
- Acceptance: When /health is ok, loop v1 MUST call Leanstral; skip generate only if docker0 is down.; Loop is splice, optional generate, lexical admit, lake compile, keep-best; hammers and TypeSafe off.; Failures retained; no Arena scores; hardware_class=spark_gb10.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-017.json

Primary execution path. Exclusive GPU client of 172.17.0.1:8080. Transfer is a hard filter; composite is tokens+elab among valid candidates. Reference proof is a legal no-op if generate is skipped.

Acceptance criteria:

1. When /health is ok, loop v1 MUST call Leanstral; skip generate only if docker0 is down.
2. Loop is splice, optional generate, lexical admit, lake compile, keep-best; hammers and TypeSafe off.
3. Failures retained; no Arena scores; hardware_class=spark_gb10.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-018 Warm-up runbook wired to verify_lra_batch

- Status: todo
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: lean_refactor_arena
- Depends on: LRA-015, LRA-017
- Goal id: LRA-S04
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S04
- Parallel lane: lra-gpu
- Outputs: papers/completion/lean_refactor_arena/harness/RUNBOOK.md, papers/completion/lean_refactor_arena/evidence/run_freeze.json, papers/completion/lean_refactor_arena/receipts/LRA-018.json
- Predicted files: papers/completion/lean_refactor_arena/harness/RUNBOOK.md, papers/completion/lean_refactor_arena/evidence/run_freeze.json, papers/completion/lean_refactor_arena/receipts/LRA-018.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-018/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/
- Resource class: gpu-leanstral
- Resource stage: execution
- Implementation timeout seconds: 7200
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-018
- Acceptance: Operator command runs 15 problems on Spark with hardware_class=spark_gb10.; Completing requires verify_lra_batch --require-complete PASS.; Does not write Arena scores into the manuscript.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-018.json

Freeze file schema plus runbook. Completing this task is not official Track 2.

Acceptance criteria:

1. Operator command runs 15 problems on Spark with hardware_class=spark_gb10.
2. Completing requires verify_lra_batch --require-complete PASS.
3. Does not write Arena scores into the manuscript.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-019 TypeSafe Jev router via in-tree typesafe_inference

- Status: todo
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: lean_refactor_arena
- Depends on: LRA-017
- Goal id: LRA-S05
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S05
- Parallel lane: lra-cpu-a
- Outputs: papers/completion/lean_refactor_arena/harness/typesafe_router.py, papers/completion/lean_refactor_arena/receipts/LRA-019.json
- Predicted files: papers/completion/lean_refactor_arena/harness/typesafe_router.py, papers/completion/lean_refactor_arena/receipts/LRA-019.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-019/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/, external/ipfs_accelerate/ipfs_accelerate_py/
- Resource class: cpu-medium
- Resource stage: execution
- Implementation timeout seconds: 7200
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-019
- Acceptance: Imports ipfs_accelerate_py.typesafe_inference, not a second typesafe_sdk client.; Default LRA_TYPESAFE=off; distill uses LRA_TYPESAFE=distill; official Track 2 stays off.; Score is a rubric index; Jev does not generate Lean.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-019.json

TYPESAFE_API_KEY will exist. Frozen ROUTE_QUESTIONS. CI fixtures without live key. Additive on top of Leanstral, not a replacement.

Acceptance criteria:

1. Imports ipfs_accelerate_py.typesafe_inference, not a second typesafe_sdk client.
2. Default LRA_TYPESAFE=off; distill uses LRA_TYPESAFE=distill; official Track 2 stays off.
3. Score is a rubric index; Jev does not generate Lean.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-020 Optional Track 1 US$3 ledger and grok adapter

- Status: todo
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: lean_refactor_arena
- Depends on: LRA-017, LRA-019
- Goal id: LRA-S06
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S06
- Parallel lane: lra-cpu-a
- Outputs: papers/completion/lean_refactor_arena/harness/track1_ledger.py, papers/completion/lean_refactor_arena/receipts/LRA-020.json
- Predicted files: papers/completion/lean_refactor_arena/harness/track1_ledger.py, papers/completion/lean_refactor_arena/receipts/LRA-020.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-020/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/
- Resource class: cpu-medium
- Resource stage: execution
- Implementation timeout seconds: 7200
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-020
- Acceptance: Hard stop at US$3/problem including Jev+grok.; Not the default winning path; skip if keys missing.; Does not contaminate Track 2 receipts.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-020.json

Closed generator is grok/grok-4.6 through llm_router.generate_text. Prepare, do not default.

Acceptance criteria:

1. Hard stop at US$3/problem including Jev+grok.
2. Not the default winning path; skip if keys missing.
3. Does not contaminate Track 2 receipts.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-021 Lake-native tactic try without snapshot_goal

- Status: todo
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: lean_refactor_arena
- Depends on: LRA-014
- Goal id: LRA-S07
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S07
- Parallel lane: lra-cpu-c
- Outputs: papers/completion/lean_refactor_arena/harness/lake_native_try.py, papers/completion/lean_refactor_arena/receipts/LRA-021.json
- Predicted files: papers/completion/lean_refactor_arena/harness/lake_native_try.py, papers/completion/lean_refactor_arena/receipts/LRA-021.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-021/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/, external/ipfs_datasets/ipfs_datasets_py/logic/hammers/
- Resource class: cpu-heavy
- Resource stage: execution
- Implementation timeout seconds: 7200
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-021
- Acceptance: Loop v2 path A uses lake env lean tactic try; does not require LeanFrontend.snapshot_goal.; Does not claim HAMMER-006 is LRA-ready.; Not on the 30 Sep critical path.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-021.json

Deferred. PATH lean --json cannot see lake-project goals.

Acceptance criteria:

1. Loop v2 path A uses lake env lean tactic try; does not require LeanFrontend.snapshot_goal.
2. Does not claim HAMMER-006 is LRA-ready.
3. Not on the 30 Sep critical path.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-022 Premise retrieval from 14 JSONL neighbors plus src lemmas

- Status: todo
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: lean_refactor_arena
- Depends on: LRA-011
- Goal id: LRA-S07
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S07
- Parallel lane: lra-cpu-b
- Outputs: papers/completion/lean_refactor_arena/harness/retrieve.py, papers/completion/lean_refactor_arena/receipts/LRA-022.json
- Predicted files: papers/completion/lean_refactor_arena/harness/retrieve.py, papers/completion/lean_refactor_arena/receipts/LRA-022.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-022/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/
- Resource class: cpu-medium
- Resource stage: execution
- Implementation timeout seconds: 3600
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-022
- Acceptance: Retrieves other warm-up proofs and lemmas mentioned in src (simp/rw/exact).; No Mathlib-scale CorpusManifest ingest.; No invented scores.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-022.json

Deferred. Do not parse Lean ourselves.

Acceptance criteria:

1. Retrieves other warm-up proofs and lemmas mentioned in src (simp/rw/exact).
2. No Mathlib-scale CorpusManifest ingest.
3. No invented scores.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-023 Optional DuckDB INSERT-only proof receipts

- Status: todo
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P2
- Track: lean_refactor_arena
- Depends on: LRA-015
- Goal id: LRA-S08
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S08
- Parallel lane: lra-cpu-b
- Outputs: papers/completion/lean_refactor_arena/harness/receipt_store.py, papers/completion/lean_refactor_arena/receipts/LRA-023.json
- Predicted files: papers/completion/lean_refactor_arena/harness/receipt_store.py, papers/completion/lean_refactor_arena/receipts/LRA-023.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-023/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/
- Resource class: cpu-medium
- Resource stage: execution
- Implementation timeout seconds: 3600
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-023
- Acceptance: INSERT-only; no DELETE of existing edges; no upsert_task of huge parent rows.; All PROOF_AUTHORITY_DIMENSIONS populated; executable_paths not primary_executable.; run_warmup.py remains the control plane.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-023.json

Learned from LA-031 ART crashes. Filesystem receipts are enough for warm-up.

Acceptance criteria:

1. INSERT-only; no DELETE of existing edges; no upsert_task of huge parent rows.
2. All PROOF_AUTHORITY_DIMENSIONS populated; executable_paths not primary_executable.
3. run_warmup.py remains the control plane.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-024 SM80 GGUF derived from Frosty40 NVFP4

- Status: blocked
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P2
- Track: lean_refactor_arena
- Depends on:
- Goal id: LRA-S09
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S09
- Parallel lane: lra-cpu-c
- Outputs: papers/completion/lean_refactor_arena/evidence/run_freeze.json, papers/completion/lean_refactor_arena/receipts/LRA-024.json
- Predicted files: papers/completion/lean_refactor_arena/evidence/run_freeze.json, papers/completion/lean_refactor_arena/receipts/LRA-024.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-024/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/
- Resource class: cpu-heavy
- Resource stage: execution
- Implementation timeout seconds: 7200
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-024
- Acceptance: Export is derived from Frosty40 revision abcc5ce2528c6375148d41dac6dce20f06c339f4 CID bafkreicgnd6su3jhmtpckbejqurdb2lchdvvydluswdg5m5zy3cpvroh3i.; New SHA recorded in evidence/run_freeze.json; do not cite unpublished SHA 3fe4e64d.; If no named 4xA100 by 2026-10-15, do not enter Track 2.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-024.json

Blocked until an operator names a cluster and produces the SM80 artifact. NVFP4-on-Spark is resource=spark_gb10 only.

Acceptance criteria:

1. Export is derived from Frosty40 revision abcc5ce2528c6375148d41dac6dce20f06c339f4 CID bafkreicgnd6su3jhmtpckbejqurdb2lchdvvydluswdg5m5zy3cpvroh3i.
2. New SHA recorded in evidence/run_freeze.json; do not cite unpublished SHA 3fe4e64d.
3. If no named 4xA100 by 2026-10-15, do not enter Track 2.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-025 Official Track 2 runner gated on cluster and SM80 GGUF

- Status: blocked
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P2
- Track: lean_refactor_arena
- Depends on: LRA-018, LRA-024
- Goal id: LRA-S09
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S09
- Parallel lane: lra-gpu
- Outputs: papers/completion/lean_refactor_arena/harness/run_official_track2.py, papers/completion/lean_refactor_arena/receipts/LRA-025.json
- Predicted files: papers/completion/lean_refactor_arena/harness/run_official_track2.py, papers/completion/lean_refactor_arena/receipts/LRA-025.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-025/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/
- Resource class: gpu-a100
- Resource stage: execution
- Implementation timeout seconds: 7200
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-025
- Acceptance: Records GPU inventory must be 4xA100 80GB; 48h wall clock; typesafe off; network=deny.; Cannot import Spark scorer aggregation.; If LRA-024 did not land by 2026-10-15, this task stays blocked.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-025.json

Gated. Spark measurements are not official Track 2 scores.

Acceptance criteria:

1. Records GPU inventory must be 4xA100 80GB; 48h wall clock; typesafe off; network=deny.
2. Cannot import Spark scorer aggregation.
3. If LRA-024 did not land by 2026-10-15, this task stays blocked.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-026 Fill manuscript measured sections from receipts only

- Status: todo
- Completion: auto
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: lean_refactor_arena
- Depends on: LRA-018
- Goal id: LRA-S10
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S10
- Parallel lane: lra-cpu-b
- Outputs: papers/completion/lean_refactor_arena/manuscript/main.tex, papers/completion/lean_refactor_arena/receipts/LRA-026.json
- Predicted files: papers/completion/lean_refactor_arena/manuscript/main.tex, papers/completion/lean_refactor_arena/receipts/LRA-026.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-026/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/
- Resource class: cpu-medium
- Resource stage: execution
- Implementation timeout seconds: 3600
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-026
- Acceptance: Approach/Models/Budget/Reproduction updated only from receipts; unrun rows stay unrun.; No invented leaderboard ranks or general token savings.; Author line remains Benjamin Barber / starworks5@gmail.com unless explicitly changed.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-026.json

If incomplete, keep unrun labels. Protocol LRA/v1 grows only if claims grow.

Acceptance criteria:

1. Approach/Models/Budget/Reproduction updated only from receipts; unrun rows stay unrun.
2. No invented leaderboard ranks or general token savings.
3. Author line remains Benjamin Barber / starworks5@gmail.com unless explicitly changed.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.

## LRA-027 Human Arena Space / OpenReview submission

- Status: blocked
- Completion: manual
- Is schedulable: false
- Review only: false
- Priority: P2
- Track: lean_refactor_arena
- Depends on: LRA-026
- Goal id: LRA-S10
- Parent goal: LRA-G000
- Objective heap: papers/completion/lean_refactor_arena/paper.objectives.md
- Board namespace: vericodegen-2026-lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S10
- Parallel lane: lra-cpu-b
- Outputs: papers/completion/lean_refactor_arena/evidence/submission_decision.json, papers/completion/lean_refactor_arena/receipts/LRA-027.json
- Predicted files: papers/completion/lean_refactor_arena/evidence/submission_decision.json, papers/completion/lean_refactor_arena/receipts/LRA-027.json, papers/completion/lean_refactor_arena/receipts/snapshots/LRA-027/
- Allowed paths: papers/completion/lean_refactor_arena/harness/, papers/completion/lean_refactor_arena/tools/, papers/completion/lean_refactor_arena/evidence/, papers/completion/lean_refactor_arena/manuscript/, papers/completion/lean_refactor_arena/receipts/
- Resource class: cpu-small
- Resource stage: execution
- Implementation timeout seconds: 3600
- Validation: python3 scripts/paper_supervisors.py verify-task --paper lean_refactor_arena --task LRA-027
- Acceptance: Not authorized for automated completion.; Human author action only.; No workflow upload.
- Paper evidence: design_win_plan.md; protocol.md LRA/v1; frozen warmup SHA-256 6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804
- Reuse candidates: papers/completion/lean_refactor_arena/design_win_plan.md, scripts/run_leanstral_ephemeral.py
- Receipt: papers/completion/lean_refactor_arena/receipts/LRA-027.json

Blocked. Completion=manual. Do not submit from a worker.

Acceptance criteria:

1. Not authorized for automated completion.
2. Human author action only.
3. No workflow upload.

Record dependencies, exact code/data/model/tool versions, actual command logs, failures and claim limitations in the receipt.
