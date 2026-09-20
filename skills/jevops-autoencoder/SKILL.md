---
name: jevops-autoencoder
description: VAE-style text→Lean IR→text round-trip. Use when scoring variations with TypeSafe Jev vs previous batch rounds, or CALL ptr://skill/port_autoencoder / port_vae / port_lean_ir. Jev replaces CE/cosine as the loss. Lake admits Lean. Never writes Lean.
---

# VAE autoencoder

`jevops.autoencoder`. CALL `ptr://skill/port_autoencoder`, `port_vae`, or `port_lean_ir`.

- Encode unstructured text to milles `mu`/`logvar`. Sample several VAE latents. Decode to sketches from a codebook of lake-ok snippets when taught.
- **Lean IR path** (`port_lean_ir`): text → `jevops-lean-ir/v1` ops → functional `theorem ident_rt : True := by` closers → text. Functional Lean only (`intro`/`simp`/`rfl`/`trivial`/`constructor`/`omega`/`decide`). No legal/modal IR families.
- **Loss is Jev**, not CE/cosine. Jev Choice/Score/Noul ranks the current variation against previous rounds in `nca.autoencoder.batch`. TypeSafe sees `cosine_m` / `ce_m` / `ir_cosine_m` / `ir_ce_m` as features.
- Cosine similarity / CE are diagnostics (`gold: false`, `loss_gold: "jev"`).
- Among Jev-ok variants, keep the shortest lake-valid body. Jev never writes Lean. Never docker0.
