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
- `lstrip_core` / `line_at` — bullet-strip and the line containing an offset.
- `pick_scored` — highest score_fn first, skip overlapping windows.
- `around_lines` — nearby lines around an index.
- `map_span_bodies` — rewrite each top-level span body; transform injected.
- `fold_following` — replace a marker line plus n following matching lines.
- `rewrite_matching_lines` — map/drop lines by stripped predicate.
- `prepend_absent` / `lines_containing` / `pop_trailing` / `any_line` — restore a missing line, find needle lines, drop trailing matches, any-line pred.
- `split_top_level` — split on `,` at depth 0; nested `([{ }])` stay in a part.
- `drop_spans` — delete `[start:end]` spans from the right (`eat_newline` optional).
- `splice_from` — replace a dst span with a src span. Missing span → dst unchanged.
- `subn_changed` — `re.subn` / Pattern.subn; return original when n==0.
- `drop_indices` — delete several line indices from the right.
- `merge_matches` — collect `(start, kind, match)` from finditer patterns, sorted by start.
- `peek_next_stripped` / `map_lines` — next non-empty line; per-line Optional rewrite.
