---
name: jevops-more-rankers
description: Extra NCA CALLs — SGD/mask/diffuse/GAN wraps, tactic Markov/HMM, isotonic Noul calibration, AdaBoost, remaining-cut quantiles, board PageRank, VAE contrastive. Use when ranking sequences, calibrating Jev, or CALL ptr://skill/port_{sgd,mask,diffuse,gan,markov,hmm,isotonic,adaboost,quantile,pagerank,contrastive}. Never writes Lean.
---

# Extra rankers

`jevops.more_rankers`. Integer milles. Lake is the oracle. Jev does not write Lean.

- **Wraps:** `port_sgd`, `port_mask`, `port_diffuse` (consumer generators via hooks).
- **GAN:** `port_gan` — generator like diffusion (perturb Lean IR / closed fills); TypeSafe Jev discriminates real vs fake. Milles fallback `cosine_m - ce_m`. Functional Lean only. Not legal-IR families. Jev is gold (`gold: false` on CE/cosine).
- **Sequence:** `port_markov` / `port_hmm` — P(next tactic head | last).
- **Calibrate:** `port_isotonic` PAVA on Noul/unsafe vs lake labels. Not an admit.
- **Residual:** `port_adaboost` milles stumps. `port_quantile` q25/50/75 remaining_cut.
- **Graph:** `port_pagerank` on `board_edges`.
- **VAE diagnostic:** `port_contrastive` milles (neg−pos+margin). Jev stays the VAE loss.

Never docker0. Dispatch `isotonic` here so it is not matched as `ica`.
