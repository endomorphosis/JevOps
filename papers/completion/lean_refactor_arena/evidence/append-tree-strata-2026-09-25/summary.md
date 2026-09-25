# Frozen Arena leaf replacement experiment

An exposed Arena incumbent, not a random canary or a training result.
Fixed profile: simp-prefix-append-tree; no retries or post-result batch expansion.

# Token/heartbeat selection

Status: CONFIRMED_LOCAL_IMPROVEMENT.

Selection objective: aggregate-local-v1; heartbeat noise floor: 100 raw units.

Evidence mode: local_lean. No production promotion, training or official score.

Selected for confirmation: composition-1.
Requests reserved: 34; native processes: 34.

| Phase | Arm | Tokens | Admissible | Raw heartbeat ranges by version/order |
| --- | --- | ---: | --- | --- |
| screen | control | 222 | True | 2607572–2607572; 2607585–2607589 |
| screen | incumbent | 172 | True | 930194–930194; 930207–930207 |
| screen | composition-0 | 170 | False | missing; missing |
| screen | composition-1 | 170 | True | 896593–896593; 896606–896606 |
| confirmation | control | 222 | True | 2607572–2607572; 2607585–2607585 |
| confirmation | incumbent | 172 | True | 930194–930194; 930207–930207 |
| confirmation | composition-1 | 170 | True | 896593–896593; 896606–896606 |

Strata follow the record's version order, reference-first then candidate-first.
All pins must verify without axiom growth. Costs use only the primary pin, in both orders.
A recommendation requires a positive conservative normalized-sum delta over both controls.
Fresh original denominators; range/floor margin; exact unrounded rational deltas in JSON.
This is a matched-local estimate, not the official score or a statistical confidence bound.
Reason: none.
