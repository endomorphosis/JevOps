---
name: jevops-mcmc
description: Generalized Metropolis-Hastings for NCA (pipeline order or custom state). Use for MCMC, MH, annealing, or CALL ptr://skill/port_mcmc. Never writes Lean. Lake is the admit oracle.
---

# Generalized MCMC

`jevops.rankers.metropolis_hastings(state, propose=, energy=, accept=None, steps=, temperature=)`.

- Default CALL `ptr://skill/port_mcmc` permutes pipeline stems. Energy is `1 − Bayes mean` plus a small position penalty. Writes `nca.pipeline_bias`.
- Hard `accept` is the lake / closed-fold constraint. Without it, MH only ranks.
- Discrete MH on NCA state, not neural sampling.

Do not emit Lean from the kernel. Do not call docker0.
