---
name: jevops-oracle
description: Order and try candidate drafts against an injected oracle. Use for try_kind, apply_round, pack_eval, lake_budget. Cache hits never admit. Never writes Lean.
---

# Oracle

Module: `jevops.oracle`. Lake (or tests) is injected.

- `order_kinds` then `try_kind` (single-flight + negative TTL).
- `apply_round` budgeted tries; repair/on_ok/on_fail are callbacks.
- `closed` / `require_named` fail closed. Cache skips never set `theorem_ok`.
