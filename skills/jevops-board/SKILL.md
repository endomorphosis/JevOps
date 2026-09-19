---
name: jevops-board
description: Generic goal/subgoal/task grid seed, status overlay, mark_ready, credit_result. Use for board_payload, overlay_ready, seed_grid_from_board. No campaign DuckDB. Never writes Lean.
---

# Board grid

Module: `jevops.board`. Consumers load a board dict (LRA: `tasks.json`).

- `ptr://goal|subgoal|task|theorem|codepath`.
- Overlay status, mark ready, credit lake results onto owning cells.
- Never campaign writes. Never docker0.
