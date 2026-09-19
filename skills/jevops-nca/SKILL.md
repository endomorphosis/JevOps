---
name: jevops-nca
description: TypeSafe NCA cell store — ptr:// ids, tick/halt, energy, overlay, mutate, dispatch_tool. Use for grid cells, neighborhoods, or CALL nca_tick / nca_fork. Never writes Lean.
---

# NCA cell store

Module: `jevops.nca`. PYTHONPATH must include JevOps.

- Cells keyed by `ptr://kind/id`. Energy clip `[0,1]`. Tick, halt, neighborhood, fork.
- `feed_with_overlays` plus residual/tree overlays. `credit_skill` from lake rows.
- `dispatch_tool` closed names; consumers pass `extras=` for walk/hook/mutate.
- `function_call_map` — Python AST defs + callees (optional qualify_fn). No source bodies.
- `call_graph_from_paths` / `append_board_edges` — qualified call graphs and NCA board edges.
- `pick_qualified` / `first_matching_symbol` — resolve a codepath name to a qualified def; first DuckDB/AST hit.
- `top_level_symbols` / `sidecar_files` / `query_sidecar_symbols` / `resolve_unique_callees`.
- `allowed_path` / `first_existing_file` — first on-disk file inside allowed roots.
- `matching_top_level` — glob Python files for function/class names containing a query.
- Cache hits never admit. Lake is the oracle. Never docker0.
