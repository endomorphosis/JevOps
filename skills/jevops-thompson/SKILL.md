---
name: jevops-thompson
description: Thompson sampling on Bayes skill posteriors. Use to explore high-variance stems or CALL ptr://skill/port_thompson. Draw is not a lake admit.
---

# Thompson sampling

`jevops.rankers.thompson_rank` samples `Beta(α,β)` per pipeline stem (two gammas).

- CALL `ptr://skill/port_thompson`. Syncs Bayes counts if empty, then writes `nca.pipeline_bias` from draws.
- Use when the mean would starve a rarely tried stem. Lake still admits. Never docker0.
