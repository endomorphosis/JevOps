# Frozen Arena leaf replacement experiment

An exposed Arena incumbent, not a random canary or a training result.
Fixed profile: subset-triple-reconstruct; no retries or post-result batch expansion.

# Token/heartbeat selection

Status: NO_IMPROVEMENT.

Selection objective: strict-dual-v1; heartbeat noise floor: 100 raw units.

Evidence mode: local_lean. No production promotion, training or official score.

Selected for confirmation: none.
Requests reserved: 20; native processes: 20.

| Phase | Arm | Tokens | Admissible | Raw heartbeat ranges by version/order |
| --- | --- | ---: | --- | --- |
| screen | control | 222 | True | 2607572–2607574; 2607585–2607595 |
| screen | incumbent | 169 | True | 1283749–1283749; 1283762–1283762 |
| screen | composition-0 | 153 | False | missing; missing |
| screen | composition-1 | 149 | False | 1644393–1644479; 1644466–1644515 |
| screen | composition-2 | 153 | False | 1821192–1821214; 1821224–1821249 |

Strata follow the record's version order, reference-first then candidate-first.
Overlapping nonconstant counts are inconclusive, not equivalent. No significance claim.
Recommendations require improvement over both original and incumbent, across every stratum.
Reason: none.
