# Frozen Arena leaf replacement experiment

An exposed Arena incumbent, not a random canary or a training result.
Fixed profile: subset-append-nested; no retries or post-result batch expansion.

# Token/heartbeat selection

Status: CONFIRMED_LOCAL_IMPROVEMENT.

Selection objective: strict-dual-v1; heartbeat noise floor: 100 raw units.

Evidence mode: local_lean. No production promotion, training or official score.

Selected for confirmation: composition-0.
Requests reserved: 46; native processes: 46.

| Phase | Arm | Tokens | Admissible | Raw heartbeat ranges by version/order |
| --- | --- | ---: | --- | --- |
| screen | control | 222 | True | 2607572–2607572; 2607585–2607585 |
| screen | incumbent | 177 | True | 1733844–1733851; 1733857–1733859 |
| screen | composition-0 | 175 | True | 1625921–1625921; 1625934–1625934 |
| screen | composition-1 | 175 | False | missing; missing |
| screen | composition-2 | 173 | False | missing; missing |
| screen | composition-3 | 173 | False | missing; missing |
| screen | composition-4 | 171 | False | missing; missing |
| confirmation | control | 222 | True | 2607572–2607572; 2607585–2607585 |
| confirmation | incumbent | 177 | True | 1733844–1733844; 1733857–1733858 |
| confirmation | composition-0 | 175 | True | 1625921–1625921; 1625934–1625936 |

Strata follow the record's version order, reference-first then candidate-first.
Overlapping nonconstant counts are inconclusive, not equivalent. No significance claim.
Recommendations require improvement over both original and incumbent, across every stratum.
Reason: none.
