# LRA native board (DuckDB + Quack)

Markdown `paper.todo.md` / `paper.objectives.md` is the **import** source.
Live scheduling is the DuckDB store:

`/home/barberb/.local/state/ipfs_accelerate_py/vericodegen-2026-lra/lean_refactor_arena/control.duckdb`

This is a **dedicated** campaign state-root. It does **not** join the default three-paper campaign (`autoformalization`, `law_to_action`, `neurosymbolic_supervision`).

## Shape

- Root goal `LRA-G000` plus 10 subgoals `LRA-S01`–`LRA-S10`
- 18 tasks `LRA-010`–`LRA-027`
- Immediate parallel ready set (no unmet deps): **LRA-010, LRA-011, LRA-012**
- GPU-exclusive later: LRA-017 / LRA-018 (HTTP client of `172.17.0.1:8080`, never `LOCK_EX`)
- Blocked: LRA-024 (SM80 GGUF), LRA-025 (official Track 2), LRA-027 (human submit)

## Commands

Validate the markdown board (parser only; `paper_supervisors.py validate` currently also imports a broken `implementation_supervisor` on ROOT):

```
python3 tests/test_lra_native_board.py
python3 papers/completion/lean_refactor_arena/tools/generate_native_board.py
```

Start a dedicated LRA campaign **after** the board is committed on branch `agent/vericodegen-2026-lean_refactor_arena` in worktree `.worktrees/vericodegen-lean_refactor_arena-2026`:

```
python3 scripts/paper_supervisor_campaign.py start \
  --state-root ~/.local/state/ipfs_accelerate_py/vericodegen-2026-lra \
  --papers lean_refactor_arena
```

Do not pass `--papers lean_refactor_arena` into the existing three-paper state-root.

## Claim boundary

No Arena scores. Spark NVFP4 ≠ official Track 2. Jev does not generate Lean. Primary path is Leanstral + `harness/run_warmup.py`.
