---
name: jevops-program
description: Closed IR compile/parse and work-ops execute. Use for program_nca, work-ops, lake/board via hooks. Never writes Lean. Lake admits.
---

# Program IR

Module: `jevops.program`.

- Closed op set. Assign-before-execute.
- Lake and board ops go through hooks. Cache hits never admit.
- Never docker0. Jev does not write Lean.
