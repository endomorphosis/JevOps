# Token/heartbeat selection

Status: CONFIRMED_LOCAL_IMPROVEMENT.

Selection objective: aggregate-local-v1; heartbeat noise floor: 100 raw units.

Evidence mode: local_lean. No production promotion, training or official score.

Selected for confirmation: merged-simp-only.
Requests reserved: 30; native processes: 30.

| Phase | Arm | Tokens | Admissible | Raw heartbeat ranges by version/order |
| --- | --- | ---: | --- | --- |
| screen | control | 222 | True | 2607572–2607574; 2607585–2607585 |
| screen | historical-260 | 185 | True | 2324397–2324397; 2324410–2324410 |
| screen | merged-simp-only | 190 | True | 2049150–2049154; 2049163–2049163 |
| confirmation | control | 222 | True | 2607572–2607578; 2607585–2607589 |
| confirmation | historical-260 | 185 | True | 2324397–2324397; 2324410–2324413 |
| confirmation | merged-simp-only | 190 | True | 2049150–2049154; 2049163–2049164 |

Strata follow the record's version order, reference-first then candidate-first.
All pins must verify without axiom growth. Costs use only the primary pin, in both orders.
A recommendation requires a positive conservative normalized-sum delta over both controls.
Fresh original denominators; range/floor margin; exact unrounded rational deltas in JSON.
This is a matched-local estimate, not the official score or a statistical confidence bound.
Reason: none.
