# Frozen Arena leaf replacement experiment

An exposed Arena incumbent, not a random canary or a training result.
Fixed profile: subset-append-shared-target; no retries or post-result batch expansion.

# Token/heartbeat selection

Status: CONFIRMED_LOCAL_IMPROVEMENT.

Selection objective: strict-dual-v1; heartbeat noise floor: 100 raw units.

Evidence mode: local_lean. No production promotion, training or official score.

Selected for confirmation: composition-2.
Requests reserved: 38; native processes: 38.

| Phase | Arm | Tokens | Admissible | Raw heartbeat ranges by version/order |
| --- | --- | ---: | --- | --- |
| screen | control | 222 | True | 2607572–2607572; 2607585–2607585 |
| screen | incumbent | 175 | True | 1625921–1625923; 1625934–1625936 |
| screen | composition-0 | 173 | False | missing; missing |
| screen | composition-1 | 173 | True | 1416750–1416751; 1416763–1416763 |
| screen | composition-2 | 169 | True | 1283749–1283749; 1283762–1283762 |
| confirmation | control | 222 | True | 2607572–2607572; 2607585–2607586 |
| confirmation | incumbent | 175 | True | 1625921–1625922; 1625934–1625934 |
| confirmation | composition-2 | 169 | True | 1283749–1283749; 1283762–1283764 |

Strata follow the record's version order, reference-first then candidate-first.
Overlapping nonconstant counts are inconclusive, not equivalent. No significance claim.
Recommendations require improvement over both original and incumbent, across every stratum.
Reason: none.
