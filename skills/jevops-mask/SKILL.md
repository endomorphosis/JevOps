---
name: jevops-mask
description: Discrete masked LM / closed-vocab text diffusion. Use for span windows, CFG score→schedule, mask_skeleton, apply_fill, shorter_fills, or CALL ptr://skill/port_mask / port_diffuse. Vocab is injected. Never writes Lean.
---

# Mask / diffusion

Module: `jevops.mask`. This is the kernel MLM: token span windows, CFG schedule, skeleton markers, strictly-shorter closed fills.

- Tokeniser, skip-line predicate, and fill vocab are injected. No Lean tables here.
- LRA `symbol_diffuse` supplies Lean vocab, PCA-line skip, and Leanstral few-shot.
- `port_mask` / `port_diffuse` fall back to this module when LRA hooks are missing.
- `port_tape_mask` is a tape editor, not this MLM. Lake admits. Never docker0.
- `filter_after_flag` — after a header/flag line, drop later lines by predicate.
- `starts_any` — stripped exact-or-prefix match (closer/tactic heads injected).
- `fold_following` — replace a marker line plus n following matching lines.
- `rewrite_matching_lines` — map/drop lines by stripped predicate.
