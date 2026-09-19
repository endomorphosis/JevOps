---
name: jevops-turing
description: Turing-machine tools on the neural tape and stack, plus a decision-transformer context packer. Use for TM step/run, tape L/R/write, stack push/pop, or CALL ptr://skill/port_{tm_step,tm_run,tm_left,tm_right,tm_write,tm_read,tm_push,tm_pop,decision_transformer}. Never writes Lean.
---

# Turing tape / stack / decision transformer

`jevops.turing` + `jevops.tape` + `jevops.tape_tools`.

- **Tape:** `read_symbol`, `poke`, `left`, `right` (bounded TAPE_N=64). Blank `_`.
- **Control:** `δ(q,a)→(q',b,L|R|S)`, `tm_step`, `tm_run` (max 32).
- **Stack:** TM aux stack plus CALL/RETURN on push/pop (`jevops.stack`).
- **Decision transformer:** `nca.dt.window` of `{state, action, symbol, rtg_m}` (last 7). Return-to-go is remaining milles steps.
- **Tape editor:** `port_tape_splice`, `port_tape_mask`, `port_tape_pop`, `port_tape_peek`, `port_tape_crop`, `port_tape_keep`, `port_tape_drop`, `port_tape_compress`, `port_tape_mark` / `port_tape_restore`, `port_tape_attn`.
- Do not match `thompson` as a TM stem. `port_tape_mask` ≠ MCA `port_mask`. Lake is the oracle. Never docker0.
