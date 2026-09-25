# Frozen Arena leaf replacement experiment

An exposed Arena incumbent, not a random canary or a training result.
Fixed profile: subset-triple-term; no retries or post-result batch expansion.

# Token/heartbeat selection

Status: NO_IMPROVEMENT.

Selection objective: aggregate-local-v1; heartbeat noise floor: 100 raw units.

Evidence mode: local_lean. No production promotion, training or official score.

Selected for confirmation: none.
Requests reserved: 16; native processes: 16.

| Phase | Arm | Tokens | Admissible | Raw heartbeat ranges by version/order |
| --- | --- | ---: | --- | --- |
| screen | control | 222 | True | 2607572–2607574; 2607585–2607585 |
| screen | incumbent | 169 | True | 1283749–1283749; 1283762–1283762 |
| screen | composition-0 | 181 | True | 1304531–1304532; 1304544–1304544 |
| screen | composition-1 | 178 | True | 1307677–1307677; 1307690–1307690 |

Strata follow the record's version order, reference-first then candidate-first.
All pins must verify without axiom growth. Costs use only the primary pin, in both orders.
A recommendation requires a positive conservative normalized-sum delta over both controls.
Fresh original denominators; range/floor margin; exact unrounded rational deltas in JSON.
This is a matched-local estimate, not the official score or a statistical confidence bound.
Reason: none.
