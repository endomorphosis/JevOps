---
name: jevops-answers
description: Unpack TypeSafe System One answers — unpack_response, choice_head, noul_attr, noul_map. Use after invoke_system_one. Score is a rubric index. Never writes Lean.
---

# Answer projectors

Module: `jevops.jev` + `jevops.pick`.

- `unpack_response` → choices, nouls, scores, usage.
- `choice_head` → probabilities, confidence, greedy choice.
- `noul_attr` / `noul_map` project Noul floats. Fired Noul is not a lake admit.
