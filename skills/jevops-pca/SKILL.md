---
name: jevops-pca
description: Integer milles PCA on tactic-count features, or CALL ptr://skill/port_pca. Not a second AST SVD. Never writes Lean.
---

# Integer PCA

`jevops.int_rankers` CALL `ptr://skill/port_pca`. Unit is milles `0..1000`.

- Integer SVD on the tactic-count matrix. Not numpy PCA.
- Float z-score SVD lives in `jevops.rankers.zscore_svd` (numpy imported lazily). LRA still owns Lean tactic-count features.
- `residual_feature_scores` is pure Python |loading × z| on minor components. `rank_present_families` keeps families whose features are present.
- Keep the PCA skeleton; MCA holes are drop candidates. Jev ranks; lake admits.

Never docker0.
