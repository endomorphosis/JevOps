# Frozen Arena leaf replacement experiment

An exposed Arena incumbent, not a random canary or a training result.
Fixed profile: subset-triple-normalize; no retries or post-result batch expansion.

# Token/heartbeat selection

Status: NO_IMPROVEMENT.

Selection objective: strict-dual-v1; heartbeat noise floor: 100 raw units.

Evidence mode: local_lean. No production promotion, training or official score.

Selected for confirmation: none.
Requests reserved: 16; native processes: 16.

| Phase | Arm | Tokens | Admissible | Raw heartbeat ranges by version/order |
| --- | --- | ---: | --- | --- |
| screen | control | 222 | True | 2607572–2607574; 2607585–2607587 |
| screen | incumbent | 169 | True | 1283749–1283749; 1283762–1283762 |
| screen | composition-0 | 163 | True | 1674338–1674340; 1674351–1674352 |
| screen | composition-1 | 161 | True | 1653905–1653905; 1653918–1653918 |

Strata follow the record's version order, reference-first then candidate-first.
Overlapping nonconstant counts are inconclusive, not equivalent. No significance claim.
Recommendations require improvement over both original and incumbent, across every stratum.
Reason: none.
