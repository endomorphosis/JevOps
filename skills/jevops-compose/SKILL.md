---
name: jevops-compose
description: CONTROL compose set for the inner walker — nest, spawn, analyze, hook, CALL, heal. Use for compose=nest/spawn/pipeline or extra_payload fork/hook. Never writes Lean. Lake admits.
---

# Compose / CONTROL

Module: `jevops.walk`. CONTROL = nest, spawn, analyze, self_improve, invoke_router, return, tick, fork, mutate, hook, call, instruct, heal.

- `compose=pipeline` applies ordered stems. `nest`/`spawn` open a child walk (FORK_MAX=4, NEST_MAX_DEPTH=3).
- `extra_payload` builds fork/hook kwargs. Halt breaks only on `budget_dead`.
- Jev does not write Lean. Never docker0.
