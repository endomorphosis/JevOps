---
name: jevops-svd
description: Truncated SVD on the theorem×skill lake matrix. Use for collaborative filtering, grid factorization, or CALL ptr://skill/port_svd. Not proof-AST PCA. Never writes Lean.
---

# Grid SVD

`jevops.rankers.recommend_svd` / CALL `ptr://skill/port_svd`.

- Matrix: theorems × portable stems, lake win +1 / fail −1.
- Truncated SVD (k≤3) reconstructs scores; unknown theorems get the mean skill row.
- Writes `nca.pipeline_bias`. Proof-style SVD is `port_pca`.
- Lake is still the oracle. Never docker0.
