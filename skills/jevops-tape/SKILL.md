---
name: jevops-tape
description: Neural tape window, splice, mask, pop, byte trim. Use for tape L0 context or CALL ptr://skill/port_tape_*. Never writes Lean. port_tape_mask is not MCA port_mask.
---

# Neural tape

Module: `jevops.tape` + `jevops.tape_tools`. Window W=7, TAPE_N=64.

- Splice/mask/pop/crop/keep/drop/compress/mark/restore/attn.
- Byte trim for context budget. TM tools live in `jevops-turing`.
- Lake is the oracle. Never docker0.
