---
name: jevops-pca
description: Integer milles PCA on tactic-count features, or CALL ptr://skill/port_pca. Not a second AST SVD. Never writes Lean.
---

# Integer PCA

`jevops.int_rankers` CALL `ptr://skill/port_pca`. Unit is milles `0..1000`.

- Integer SVD on the tactic-count matrix. Not numpy PCA.
- Proof-style float SVD of Lean tactic counts (MCA residuals) stays in the consumer (`pca_mca_fanout` for LRA).
- Keep the PCA skeleton; MCA holes are drop candidates. Jev ranks; lake admits.

Never docker0.
