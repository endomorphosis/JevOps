---
name: jevops-tactics
description: Lean tactic-block analysis — case spans, PCA/MCA drops, MCA holes, hammer repair, Inits kernels. Use when masking residuals, counting tactics, or replaying Core.InitsUpdatesComm. Lake is the oracle. Never writes Lean.
---

# Lean tactics

Modules: `jevops.tactics`, `jevops.inits`, `jevops.lean`, `jevops.folds`, `jevops.binders`.

- `case_spans` / `collapse_simp_at` / `drop_have_obtain` / `count_tactics`
- MCA `find_holes` / `mask_mca` / `template_fill` / `hammer_repair`
- Symbol vocab: `OPERATORS`, `PHRASE_ALTS`, `LEAN_TACTICS`, `PCA_KEEP_PREFIXES`
- `jevops.inits` — Core.InitsUpdatesComm 268→139 string kernels (`replay` / `propose`)
- `extract_src_lemmas` — regex lemmas from `simp [` / `rw [` / `exact` / `apply`
- MCMC edits: `join_consecutive_applies`, `collapse_ih_simps`, `drop_last_bare_simp_all`
- Constrained beam: `pca_case_tags`, `looks_like_tactic`, `stop_allowed`, `insert_haves_before_induction`
- Closed drafts: `HAMMER_BODIES`, `closed_tree_edits`, `span_preserving_edits`, `guided_mca_edits`
- `jevops.lean.extract_generated_tactics` / `parse_next_tactic_line` — untrusted model payload → one tactic line
- `jevops.lean.VersionPin` / `lake_candidate_source` / `tactic_block_from_body`

Jev does not write Lean. Lake admits. Never docker0.
