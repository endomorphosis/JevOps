---
name: jevops-mca
description: MCA residual line-run holes — scan_line_holes, mask_skeleton, fill_subset, rank_cap. Use for port_mask / hole ablation. Hole matchers are injected. Never writes Lean. Lake admits.
---

# MCA holes

Module: `jevops.mask`. Consecutive line runs become holes. Marker/fill functions are injected.

- LRA `mca_mask_replace` still owns Lean regexes (simp-at, rw, rename_i, have) and template fills.
- `rewrite_runs` / `drop_matching_line` / `join_consecutive_lines` / `filter_keepends` — line-run edits.
- `fill_subset` drops chosen holes. Ablation that lakes stays in the consumer.
- PCA skeleton skip is the consumer's match predicate. Never docker0.
