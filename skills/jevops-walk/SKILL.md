---
name: jevops-walk
description: Inner TypeSafe walker — compose dispatch, ptr CALL, nest/spawn, admit_step. Use for CONTROL compose, inner_loop, or pack_canary. Never writes Lean. Lake admits.
---

# Inner walk

Module: `jevops.walk`. Implementations inject lake/Jev HTTP.

- CONTROL compose set. Halt breaks only on `budget_dead`.
- `inner_loop`, `handle_ptr_call`, `admit_step`, `extra_payload` for fork/hook.
- `pack_canary` / `run_sampled`. Cache hits never admit Lean. Never docker0.
