# Lean Refactor Arena — review notes

Sources used 2026-09-16:

- https://delta-lab-ai-lean-refactor-arena.hf.space/gradio_api/file=/tmp/gradio/3389f2fbc0397df3689218ee1bc68f1c47c0721bae28e0e7aaa5a5ea503b4e94/benchmark_data_warmup.jsonl
- https://huggingface.co/spaces/delta-lab-ai/lean-refactor-arena
- https://vericodegen.github.io/
- https://leanrefactor.github.io/
- `papers/completion/lean_refactor_arena/design_win_plan.md` (rev. 4)

Template: `neurips_2026_vericode_workshop_competition.tex` + `neurips_2026_vericode_competition.sty`.

## Hard constraints

- Four required headings in order: Approach, Models, Budget accounting, Reproduction.
- Single-blind: Benjamin Barber / starworks5@gmail.com.
- Lean is the only correctness oracle. TypeSafe Jev does not generate Lean.
- Primary path: Leanstral on live docker0 (`172.17.0.1:8080`) + in-repo `harness/run_warmup.py`.
- Never `LOCK_EX` on `gpu-0.lock`. Never a second `llama-server`.
- Do not report unrun stages as complete. Do not invent Arena scores. Spark NVFP4 is not official Track 2.
- Native board lives in DuckDB+Quack under dedicated campaign state-root `vericodegen-2026-lra`. Do not add this paper to the default three-paper campaign start.

## Evidence status

| Claim | Status |
| --- | --- |
| 15-problem warm-up census | Measured (frozen JSONL SHA-256 `6209680c…`) |
| Native goal/task board | Imported; harness tasks LRA-010–LRA-027 |
| Leanstral refactoring loop | Specified, unrun (LRA-017) |
| Official 4×A100 Track 2 run | Blocked (LRA-024/025) |
| Arena Space submission | Manual / blocked (LRA-027) |

## Historical scaffold (not re-imported)

LRA-001–LRA-004 (JSONL freeze, census, manuscript, PDF) already completed before this native board. Bootstrap cannot import `done`/`completed` tasks; they stay in git history and the PDF, not as live Quack rows.
