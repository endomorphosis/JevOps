---
name: jevops-jev
description: TypeSafe Choice/Score/Noul projectors and fixtures. Use for instantiate_questions, skip_reason, invoke_system_one, or deny_lean_keys. Jev is a gate, not a generator. Never writes Lean.
---

# Jev projectors

Module: `jevops.jev`. Implementations own question catalogs and hosted HTTP.

- Score is a rubric index, not a probability.
- `skip_reason` / `skipped` fail closed. `deny_lean_keys` strips Lean/Arena fields.
- `invoke_system_one` times `client.system_one` (context managers ok).
- Jev does not choose the next action. Never docker0.
