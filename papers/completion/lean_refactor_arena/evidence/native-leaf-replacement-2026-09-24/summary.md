# Frozen Arena leaf replacement experiment

An exposed Arena incumbent, not a random canary or a training result.
Fixed first-leaf/all-leaf candidates; no retries or post-result batch expansion.

# Token/heartbeat selection

Status: NO_IMPROVEMENT.

Selection objective: strict-dual-v1; heartbeat noise floor: 100 raw units.

Evidence mode: local_lean. No production promotion, training or official score.

Selected for confirmation: none.
Requests reserved: 16; native processes: 16.

| Phase | Arm | Tokens | Admissible | Raw heartbeat ranges by version/order |
| --- | --- | ---: | --- | --- |
| screen | control | 222 | True | 2607572–2607572; 2607585–2607585 |
| screen | historical-260 | 185 | True | 2324397–2324397; 2324410–2324411 |
| screen | composition-0 | 184 | False | missing; missing |
| screen | composition-1 | 176 | False | missing; missing |

Strata follow the record's version order, reference-first then candidate-first.
Overlapping nonconstant counts are inconclusive, not equivalent. No significance claim.
Recommendations require improvement over both original and incumbent, across every stratum.
Reason: none.
