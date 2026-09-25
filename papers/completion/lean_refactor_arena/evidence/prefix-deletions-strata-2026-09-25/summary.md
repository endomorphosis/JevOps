# Frozen Arena leaf replacement experiment

An exposed Arena incumbent, not a random canary or a training result.
Fixed profile: simp-prefix-single-deletions; no retries or post-result batch expansion.

# Token/heartbeat selection

Status: CONFIRMED_LOCAL_IMPROVEMENT.

Selection objective: aggregate-local-v1; heartbeat noise floor: 100 raw units.

Evidence mode: local_lean. No production promotion, training or official score.

Selected for confirmation: composition-2.
Requests reserved: 42; native processes: 42.

| Phase | Arm | Tokens | Admissible | Raw heartbeat ranges by version/order |
| --- | --- | ---: | --- | --- |
| screen | control | 222 | True | 2607572–2607572; 2607585–2607585 |
| screen | incumbent | 170 | True | 896593–896593; 896606–896606 |
| screen | composition-0 | 168 | False | missing; missing |
| screen | composition-1 | 168 | True | 858212–858212; 858225–858225 |
| screen | composition-2 | 168 | True | 790126–790126; 790139–790139 |
| screen | composition-3 | 168 | False | missing; missing |
| confirmation | control | 222 | True | 2607572–2607573; 2607585–2607585 |
| confirmation | incumbent | 170 | True | 896593–896593; 896606–896606 |
| confirmation | composition-2 | 168 | True | 790126–790126; 790139–790139 |

Strata follow the record's version order, reference-first then candidate-first.
All pins must verify without axiom growth. Costs use only the primary pin, in both orders.
A recommendation requires a positive conservative normalized-sum delta over both controls.
Fresh original denominators; range/floor margin; exact unrounded rational deltas in JSON.
This is a matched-local estimate, not the official score or a statistical confidence bound.
Reason: none.
