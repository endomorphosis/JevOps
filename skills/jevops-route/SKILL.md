---
name: jevops-route
description: TypeSafe route result packing — stringify legends, skip_reason, distill_row. Use for RouteResult.as_dict or distill logs. Never writes Lean. Score is a rubric index.
---

# Route / distill packing

Module: `jevops.jev`.

- `stringify_legend_keys` makes legend maps JSON-safe.
- `keys_by_type` splits a question spec into score/noul/choice keys.
- `skip_reason` / `distill_row` / `deny_lean_keys`. Hosted HTTP stays in the consumer.
- Never docker0. Jev does not write Lean.
