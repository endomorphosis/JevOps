---
name: jevops-temporal
description: Milles Hawkes, CRF, submodular CALL-sets, delayed bandits, tape conv/DFT. Use when recency, sequence tagging, budgeted CALL sets, delayed lake, or tape locality matter. CALL ptr://skill/port_{hawkes,crf,submodular,delayed_bandit,tape_conv,tape_fft}. Never writes Lean.
---

# Temporal and budget skills

`jevops.temporal`. Integer milles.

| CALL | Job |
| --- | --- |
| `port_hawkes` | λ = μ + Σ α/(1+βΔt) from lake event times |
| `port_crf` | Viterbi on tactic heads (unary + bigrams) |
| `port_submodular` | Greedy residual cover, budget K CALLs |
| `port_delayed_bandit` | UCB with pending (unresolved lake) pulls |
| `port_tape_conv` / `port_tape_fft` | Conv / 7-point DFT on tape window |

Lake is the oracle. Jev does not write Lean. Never docker0.
