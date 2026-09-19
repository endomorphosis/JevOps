---
name: jevops-budget
description: Inner walk step/depth budget and context trim. Use for inner_budget, context_budget, or halt budget_dead. Cache hits never admit. Never writes Lean.
---

# Budget

Modules: `jevops.outer`, `jevops.kernel`, `jevops.walk`.

- `inner_budget` → (max_steps, max_depth) from args. INNER_MAX_STEPS=8, NEST_MAX_DEPTH=3.
- Context budget trims tape bytes and the DT window.
- Halt requires ever_ran or budget_dead; inner walk only **breaks** on budget_dead.
- Never docker0.
