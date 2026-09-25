# Frozen Arena leaf replacement experiment

An exposed Arena incumbent, not a random canary or a training result.
Fixed profile: subset-append; no retries or post-result batch expansion.

# Token/heartbeat selection

Status: CONFIRMED_LOCAL_IMPROVEMENT.

Selection objective: strict-dual-v1; heartbeat noise floor: 100 raw units.

Evidence mode: local_lean. No production promotion, training or official score.

Selected for confirmation: composition-2.
Requests reserved: 38; native processes: 38.

| Phase | Arm | Tokens | Admissible | Raw heartbeat ranges by version/order |
| --- | --- | ---: | --- | --- |
| screen | control | 222 | True | 2607572–2607572; 2607585–2607595 |
| screen | historical-260 | 185 | True | 2324397–2324397; 2324410–2324410 |
| screen | composition-0 | 183 | True | 2096663–2096663; 2096676–2096676 |
| screen | composition-1 | 183 | False | missing; missing |
| screen | composition-2 | 181 | True | 1867773–1867780; 1867788–1867788 |
| confirmation | control | 222 | True | 2607572–2607572; 2607585–2607585 |
| confirmation | historical-260 | 185 | True | 2324397–2324399; 2324410–2324413 |
| confirmation | composition-2 | 181 | True | 1867773–1867773; 1867786–1867788 |

Strata follow the record's version order, reference-first then candidate-first.
Overlapping nonconstant counts are inconclusive, not equivalent. No significance claim.
Recommendations require improvement over both original and incumbent, across every stratum.
Reason: none.
