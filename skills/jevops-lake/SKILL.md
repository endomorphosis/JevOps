---
name: jevops-lake
description: Budgeted oracle round — order_kinds, try_kind, apply_round, lake_budget, credit_skill. Use when lake-trying leftover drafts. Cache hits never admit. Never writes Lean.
---

# Lake round

Modules: `jevops.oracle`, `jevops.nca`.

- `lake_budget` gives 1 slot when too_big, else lake_top.
- `apply_round` injects compile/repair/on_ok/on_fail. Negative TTL / in_flight never admit.
- `credit_skill` upserts a skill cell from the row. Keep-best file writes stay in the consumer.
