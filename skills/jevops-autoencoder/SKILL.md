---
name: jevops-autoencoder
description: VAE-style text→Lean round-trip. Use when scoring variations with TypeSafe Jev vs previous batch rounds, or CALL ptr://skill/port_autoencoder / port_vae. Jev replaces CE/cosine as the loss. Lake admits Lean. Never writes Lean.
---

# VAE autoencoder

`jevops.autoencoder`. CALL `ptr://skill/port_autoencoder` or `port_vae`.

- Encode unstructured text to milles `mu`/`logvar`. Sample several VAE latents. Decode to sketches from a codebook of lake-ok snippets when taught.
- **Loss is Jev**, not CE/cosine. Jev Choice/Score/Noul ranks the current variation against previous rounds in `nca.autoencoder.batch`.
- Cosine similarity / cosine loss are diagnostics (`gold: false`).
- Among Jev-ok variants, keep the shortest lake-valid body. Jev never writes Lean. Never docker0.
