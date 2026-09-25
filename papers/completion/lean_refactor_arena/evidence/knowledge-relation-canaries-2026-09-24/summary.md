# Protected relation canary smoke test

Synthetic post-development cases, not a blind dataset or an all-15 Arena score.

Native paired coverage: 4/6; strict joint improvements: 3/6.

| Case | Inferred proposal | Compact local tokens | Inferred tokens | Heartbeats vs local | Run |
| --- | --- | ---: | ---: | --- | --- |
| and-assoc | PROPOSED | 27 | 1 | LOWER_IN_BOTH_ORDERS | COMPLETE |
| or-assoc | SEARCH_BUDGET | 81 | 67 | INCOMPLETE | COMPLETE |
| and-or-distrib | PROPOSED | 66 | 1 | LOWER_IN_BOTH_ORDERS | COMPLETE |
| or-and-distrib | SEARCH_BUDGET | 56 | 56 | INCOMPLETE | COMPLETE |
| nested-or-swap | PROPOSED | 16 | 5 | LOWER_IN_BOTH_ORDERS | COMPLETE |
| three-edge-permutation | PROPOSED | 9 | 17 | LOWER_IN_BOTH_ORDERS | COMPLETE |

All frozen cases stay in the denominator. No training, promotion, model calls, or outcome-dependent tuning.
The ledger consumes these alpha groups even on partial failure; future reuse is regression, not a fresh canary.
