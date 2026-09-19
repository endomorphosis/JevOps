---
name: jevops-stack
description: ptr:// CALL/RETURN stack for nested skill walks. Use for CALL frames, max depth, or TM aux stack. Never writes Lean.
---

# CALL stack

Module: `jevops.stack`. MAX_DEPTH=3.

- Frames for skill|family|theorem|module|tool|cell|subloop|mcpplusplus|goal|subgoal|task|codepath.
- Push/pop with RETURN. Used by inner walk and TM aux stack.
- Never docker0. Jev does not write Lean.
