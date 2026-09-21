# LRA protocol: Lean Refactor Arena competition report

**Protocol version:** `LRA/v1`, frozen 2026-09-16. **Execution state:** warm-up JSONL imported and characterized; JevOps now contains the executable harness and has passed deterministic/synthetic self-checks, but no complete scored refactoring run has been performed. This is not a research-track paper and is not a ranked Arena entry.

## Claim boundary

Allowed measured claims:

- The frozen file `data/benchmark_data_warmup.jsonl` has SHA-256 `6209680cf00cde0765b77b24834cd72c64dd585b2f7e3f2a58209980ab59a804`, 15 records, 113826 bytes.
- Source counts, proof-length min/max/mean, line-count min/max/mean, toolchain tags, and repository URLs as emitted by `tools/summarize_warmup.py`.

Forbidden unless a later protocol version is frozen *before* the run:

- Arena leaderboard scores, official Track 1 or Track 2 rankings.
- Token savings, elaboration reductions, or version-transfer scores.
- Treating DGX Spark GB10 wall-clock as the official 4×A100 80 GB / 48 h envelope.
- Marking the benchmark measured because a plan, self-check, or synthetic compile passed.
- OpenReview submission or Space upload by this workflow.

## Tracks

| Track | Resource cap | This report |
| --- | --- | --- |
| 1 Closed | ≤ US$3 API / problem | Unused; $0 API |
| 2 Open | ≤ 4×A100 80 GB, ≤ 48 h full benchmark | Specified; unrun |

## Scoring axes (organizer-defined, unmeasured here)

1. Proof-source token count vs the reference proof.
2. Lean elaboration effort.
3. Zero-shot version transfer across JSONL `version_info` snapshots.

Lean is the only correctness oracle. Statement changes are invalid.

## Reproduction

`python3 papers/completion/lean_refactor_arena/tools/summarize_warmup.py` must exit 0 on the frozen digest. The JevOps experimental bridge may emit candidate receipts for research, but it never emits official Arena scores or changes the frozen JSONL.

## Completion

A later harness run is `measured` only with per-problem compile receipts, retained failures, and hardware/wall-clock logs. Negative and incomplete outcomes stay negative and incomplete.
