---
name: jevops-lake
description: Budgeted oracle round and lake-compile helpers — order_kinds, apply_round, measurement_argv, parse_axioms, lake_measurement_ok. Use when lake-trying leftover drafts. Cache hits never admit. Never writes Lean.
---

# Lake round

Modules: `jevops.oracle`, `jevops.nca`, `jevops.lean`.

- `lake_budget` gives 1 slot when too_big, else lake_top.
- `apply_round` injects compile/repair/on_ok/on_fail. Negative TTL / in_flight never admit.
- `credit_skill` upserts a skill cell from the row. Keep-best file writes stay in the consumer.
- `jevops.lean.measurement_argv` / `parse_axioms` / `lake_measurement_ok` / `fill_from_process` / `overlay_measurement` — tag-pinned `lake env lean --json`. IndependentKernelVerifier is not the oracle.
- Path A closers: `path_a_tactics` (`rfl`/`decide`/`omega`/`simp_all`, plus `aesop` when imported).
- `compile_closed` — fail-closed compile payload when no matching toolchain is installed.
- `render_mathlib_aesop_lakefile` / `materialize_lake_files` / `write_lake_source` — Putnam/Mathlib lake project files. Never `Tmp.lean`.
- `ExecutablePaths` — tag-pinned lean+lake pair.
- `BakeJob` / `PutnamPin` — one olean/Putnam bake unit and Mathlib+Aesop pin. Plan order (Strata first) stays in the consumer.
- `jevops.folds` — portable Lean tactic folds. `jevops.binders` — unused-binder gates and Unknown identifier repair.

Jev does not write Lean. Lake admits. Never docker0.
