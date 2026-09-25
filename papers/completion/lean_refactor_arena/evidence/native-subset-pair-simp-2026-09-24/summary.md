# Frozen Arena leaf replacement experiment

An exposed Arena incumbent, not a random canary or a training result.
Fixed profile: subset-append-simp; no retries or post-result batch expansion.

# Token/heartbeat selection

Status: NO_IMPROVEMENT.

Selection objective: strict-dual-v1; heartbeat noise floor: 100 raw units.

Evidence mode: local_lean. No production promotion, training or official score.

Selected for confirmation: none.
Requests reserved: 24; native processes: 24.

| Phase | Arm | Tokens | Admissible | Raw heartbeat ranges by version/order |
| --- | --- | ---: | --- | --- |
| screen | control | 222 | True | 2607572–2607572; 2607585–2607587 |
| screen | incumbent | 169 | True | 1283749–1283749; 1283762–1283764 |
| screen | composition-0 | 159 | False | missing; missing |
| screen | composition-1 | 123 | False | missing; missing |
| screen | composition-2 | 161 | True | 1720073–1720073; 1720086–1720086 |
| screen | composition-3 | 131 | False | missing; missing |

Strata follow the record's version order, reference-first then candidate-first.
Overlapping nonconstant counts are inconclusive, not equivalent. No significance claim.
Recommendations require improvement over both original and incumbent, across every stratum.
Reason: none.
