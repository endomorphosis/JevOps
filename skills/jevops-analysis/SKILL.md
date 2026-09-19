---
name: jevops-analysis
description: Compact proof analysis rows and MCA hole projections for Jev/rankers. Use for analysis_row, hole_rows, pick_state. Never writes Lean. Lake admits.
---

# Analysis rows

Module: `jevops.pick`.

- `analysis_row` packs name/source/tokens/counts/families/holes.
- `hole_rows` projects hole objects via injected token/used/safe fns.
- Consumer fills Lean-specific counts (PCA/MCA). Jev ranks; lake admits.
