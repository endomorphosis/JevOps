---
name: jevops-fills
description: Parse <<<id attr=...>>> fill blocks from a model reply. Use for parse_marked_fills after Leanstral/Grok hole-fill. Never writes Lean. Lake admits.
---

# Marked fills

Module: `jevops.mask.parse_marked_fills`.

- Holes may be dicts or objects with `hole_id` and `kind`/`family`.
- Optional `fallback_fn` for a whole-block reply (`__full__`).
- LRA `symbol_diffuse` / `mca_mask_replace` still own prompts and Leanstral HTTP.
