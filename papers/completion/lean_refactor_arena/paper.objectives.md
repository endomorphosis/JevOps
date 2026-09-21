# Lean Refactor Arena — objective heap

Reviewed scope: `papers/completion/lean_refactor_arena/review.md`. Executable board: `papers/completion/lean_refactor_arena/paper.todo.md`.

A completed LRA board means Leanstral + in-repo `run_warmup.py` ran on this machine under Lean-as-oracle,
with fail-closed receipts and no invented Arena scores. It does not mean official Track 2, OpenReview upload,
or treating Spark NVFP4 wall-clock as 4×A100.

## LRA-G000 Complete the Leanstral local harness and honest competition report

- Status: active
- Parent:
- Depends on:
- Fib priority: 1
- Priority: P0
- Track: lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-G000
- Goal: Ship a Leanstral-backed local harness in this repo that rewrites warm-up proof bodies under Lean-as-oracle, without inventing Arena scores or treating Spark NVFP4 wall-clock as official Track 2.
- Outputs: papers/completion/lean_refactor_arena/harness/generate_text.py, papers/completion/lean_refactor_arena/harness/lra_prompt.txt, papers/completion/lean_refactor_arena/harness/splice.py, papers/completion/lean_refactor_arena/harness/test_splice.py, external/ipfs_datasets/ipfs_datasets_py/logic/hammers/frontends/lean_toolchain.py, papers/completion/lean_refactor_arena/harness/putnam_lake/README.md, papers/completion/lean_refactor_arena/harness/bake_oleans.py, papers/completion/lean_refactor_arena/harness/compile_worker.py, papers/completion/lean_refactor_arena/tools/verify_lra_batch.py, papers/completion/lean_refactor_arena/harness/docker0_client.py, papers/completion/lean_refactor_arena/harness/run_warmup.py, papers/completion/lean_refactor_arena/harness/RUNBOOK.md, papers/completion/lean_refactor_arena/evidence/run_freeze.json, papers/completion/lean_refactor_arena/harness/typesafe_router.py, papers/completion/lean_refactor_arena/harness/track1_ledger.py, papers/completion/lean_refactor_arena/harness/lake_native_try.py, papers/completion/lean_refactor_arena/harness/retrieve.py, papers/completion/lean_refactor_arena/harness/receipt_store.py, papers/completion/lean_refactor_arena/harness/run_official_track2.py, papers/completion/lean_refactor_arena/manuscript/main.tex, papers/completion/lean_refactor_arena/evidence/submission_decision.json
- Gap task: LRA-010, LRA-011, LRA-012, LRA-013, LRA-014, LRA-015, LRA-016, LRA-017, LRA-018, LRA-019, LRA-020, LRA-021, LRA-022, LRA-023, LRA-024, LRA-025, LRA-026, LRA-027
- Acceptance: Linked task criteria have current artifact and validation evidence; numerical claims trace to real runs; unrun official rows stay unrun.
- Validation: python3 scripts/paper_supervisors.py verify-goal --paper lean_refactor_arena --goal LRA-G000

## LRA-S01 Leanstral generate_text and docker0 HTTP client

- Status: active
- Parent: LRA-G000
- Depends on:
- Fib priority: 2
- Priority: P0
- Track: lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S01
- Goal: Fail-closed generate_text against live docker0 Leanstral; never LOCK_EX; never a second llama-server.
- Outputs: papers/completion/lean_refactor_arena/harness/generate_text.py, papers/completion/lean_refactor_arena/harness/lra_prompt.txt, papers/completion/lean_refactor_arena/harness/docker0_client.py
- Gap task: LRA-010, LRA-016
- Acceptance: Linked task criteria have current artifact and validation evidence; numerical claims trace to real runs; unrun official rows stay unrun.
- Validation: python3 scripts/paper_supervisors.py verify-goal --paper lean_refactor_arena --goal LRA-S01

## LRA-S02 Prefix splice and lexical admission

- Status: active
- Parent: LRA-G000
- Depends on:
- Fib priority: 3
- Priority: P0
- Track: lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S02
- Goal: Bind statement via src.startswith(statement) on all 15 warm-up records; admit tactic blocks only.
- Outputs: papers/completion/lean_refactor_arena/harness/splice.py, papers/completion/lean_refactor_arena/harness/test_splice.py
- Gap task: LRA-011
- Acceptance: Linked task criteria have current artifact and validation evidence; numerical claims trace to real runs; unrun official rows stay unrun.
- Validation: python3 scripts/paper_supervisors.py verify-goal --paper lean_refactor_arena --goal LRA-S02

## LRA-S03 Lake compile toolchain and dedicated verifier

- Status: active
- Parent: LRA-G000
- Depends on:
- Fib priority: 4
- Priority: P0
- Track: lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S03
- Goal: Pin elan tags, bake oleans, compile one Strata file then all tags, fail-closed verify_lra_batch.
- Outputs: external/ipfs_datasets/ipfs_datasets_py/logic/hammers/frontends/lean_toolchain.py, papers/completion/lean_refactor_arena/harness/putnam_lake/README.md, papers/completion/lean_refactor_arena/harness/bake_oleans.py, papers/completion/lean_refactor_arena/harness/compile_worker.py, papers/completion/lean_refactor_arena/tools/verify_lra_batch.py
- Gap task: LRA-012, LRA-013, LRA-014, LRA-015
- Acceptance: Linked task criteria have current artifact and validation evidence; numerical claims trace to real runs; unrun official rows stay unrun.
- Validation: python3 scripts/paper_supervisors.py verify-goal --paper lean_refactor_arena --goal LRA-S03

## LRA-S04 Warm-up loop v1 on this machine

- Status: active
- Parent: LRA-G000
- Depends on:
- Fib priority: 5
- Priority: P0
- Track: lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S04
- Goal: run_warmup.py: splice, Leanstral when /health is ok, lexical admit, lake compile, keep-best. Unscored.
- Outputs: papers/completion/lean_refactor_arena/harness/run_warmup.py, papers/completion/lean_refactor_arena/harness/RUNBOOK.md, papers/completion/lean_refactor_arena/evidence/run_freeze.json
- Gap task: LRA-017, LRA-018
- Acceptance: Linked task criteria have current artifact and validation evidence; numerical claims trace to real runs; unrun official rows stay unrun.
- Validation: python3 scripts/paper_supervisors.py verify-goal --paper lean_refactor_arena --goal LRA-S04

## LRA-S05 TypeSafe Jev distill after v1

- Status: active
- Parent: LRA-G000
- Depends on:
- Fib priority: 6
- Priority: P1
- Track: lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S05
- Goal: Optional typed gates via ipfs_accelerate_py.typesafe_inference. Off on official Track 2.
- Outputs: papers/completion/lean_refactor_arena/harness/typesafe_router.py
- Gap task: LRA-019
- Acceptance: Linked task criteria have current artifact and validation evidence; numerical claims trace to real runs; unrun official rows stay unrun.
- Validation: python3 scripts/paper_supervisors.py verify-goal --paper lean_refactor_arena --goal LRA-S05

## LRA-S06 Optional Track 1 budget path

- Status: active
- Parent: LRA-G000
- Depends on:
- Fib priority: 7
- Priority: P1
- Track: lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S06
- Goal: Prepare grok+Jev in-loop under US$3/problem. Not the default winning path.
- Outputs: papers/completion/lean_refactor_arena/harness/track1_ledger.py
- Gap task: LRA-020
- Acceptance: Linked task criteria have current artifact and validation evidence; numerical claims trace to real runs; unrun official rows stay unrun.
- Validation: python3 scripts/paper_supervisors.py verify-goal --paper lean_refactor_arena --goal LRA-S06

## LRA-S07 Deferred lake-native hammers and JSONL retrieval

- Status: active
- Parent: LRA-G000
- Depends on:
- Fib priority: 8
- Priority: P1
- Track: lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S07
- Goal: Loop v2 only. Do not claim LeanFrontend.snapshot_goal is lake-ready.
- Outputs: papers/completion/lean_refactor_arena/harness/lake_native_try.py, papers/completion/lean_refactor_arena/harness/retrieve.py
- Gap task: LRA-021, LRA-022
- Acceptance: Linked task criteria have current artifact and validation evidence; numerical claims trace to real runs; unrun official rows stay unrun.
- Validation: python3 scripts/paper_supervisors.py verify-goal --paper lean_refactor_arena --goal LRA-S07

## LRA-S08 Optional INSERT-only proof receipts

- Status: active
- Parent: LRA-G000
- Depends on:
- Fib priority: 9
- Priority: P1
- Track: lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S08
- Goal: Filesystem receipts remain authority for warm-up. DuckDB INSERT-only if used.
- Outputs: papers/completion/lean_refactor_arena/harness/receipt_store.py
- Gap task: LRA-023
- Acceptance: Linked task criteria have current artifact and validation evidence; numerical claims trace to real runs; unrun official rows stay unrun.
- Validation: python3 scripts/paper_supervisors.py verify-goal --paper lean_refactor_arena --goal LRA-S08

## LRA-S09 Official Track 2 gate

- Status: active
- Parent: LRA-G000
- Depends on:
- Fib priority: 10
- Priority: P1
- Track: lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S09
- Goal: SM80 GGUF derived from Frosty40 NVFP4 plus named 4xA100 by 2026-10-15, or do not enter Track 2.
- Outputs: papers/completion/lean_refactor_arena/evidence/run_freeze.json, papers/completion/lean_refactor_arena/harness/run_official_track2.py
- Gap task: LRA-024, LRA-025
- Acceptance: Linked task criteria have current artifact and validation evidence; numerical claims trace to real runs; unrun official rows stay unrun.
- Validation: python3 scripts/paper_supervisors.py verify-goal --paper lean_refactor_arena --goal LRA-S09

## LRA-S10 Manuscript measured section and human submission

- Status: active
- Parent: LRA-G000
- Depends on:
- Fib priority: 11
- Priority: P1
- Track: lean_refactor_arena
- Bundle: lean_refactor_arena/LRA-S10
- Goal: Fill Approach/Models/Budget only from receipts. Submission is manual.
- Outputs: papers/completion/lean_refactor_arena/manuscript/main.tex, papers/completion/lean_refactor_arena/evidence/submission_decision.json
- Gap task: LRA-026, LRA-027
- Acceptance: Linked task criteria have current artifact and validation evidence; numerical claims trace to real runs; unrun official rows stay unrun.
- Validation: python3 scripts/paper_supervisors.py verify-goal --paper lean_refactor_arena --goal LRA-S10
