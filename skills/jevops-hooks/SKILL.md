---
name: jevops-hooks
description: Optional consumer callbacks so the kernel never imports Lean/lake modules. Use for register/resolve/try_import of load_board, token_count, eval_theorem. Never writes Lean.
---

# Hooks

Module: `jevops.hooks`. Kernel never requires them.

- `register(name, fn)` / `resolve` / `const` / `try_import`.
- Missing hooks fail closed. Consumers (LRA) register in `_jevops_hooks.py`.
- Never docker0. Jev does not write Lean.
