# Training-only graph refinement and frozen transfer

Generated from receipts, not fresh verification or an arena result.

Selected solely on training data: `multiscale_batch_0.15`. Epochs: 80.
Same examples/pass; batch averages before clipping and has fewer optimizer updates than online.

| Transfer arm | Valid / total | Verified saved tokens | Edit CE | Expected cosine loss |
| --- | --- | --- | --- | --- |
| multiscale_batch_0.15 | 8/8 | 48 | 0.676686 | 0.491486 |
| last_online_0.15 | 4/8 | 64 | 0.692581 | 0.499682 |
| fixed_graph | 8/8 | 48 | 0.629833 | 0.463424 |
| frozen_multiscale | 8/8 | 48 | 0.677439 | 0.491881 |
| node_bag | 8/8 | 48 | 0.68061 | 0.493536 |

| Split | Selected / fixed saved tokens | Selected / fixed CE | Selected / fixed cosine loss |
| --- | --- | --- | --- |
| validation | 16 / 16 | 0.667843 / 0.673288 | 0.486911 / 0.489752 |
| canary | 16 / 0 | 0.671165 / 0.68622 | 0.488603 / 0.492222 |
| holdout | 16 / 32 | 0.683868 / 0.579912 | 0.495216 / 0.435861 |

Gates: `{"all_splits_pass": false, "baseline_complete_loss_coverage": true, "baseline_savings_nonregression": true, "complete_cost_and_loss_coverage": true, "complete_validity": true, "cross_entropy_nonregression": false, "expected_cosine_loss_nonregression": false}`.
Fresh goal layouts with disjoint family labels and name-insensitive type/proof hashes; same alias/rfl task.
Not mathematical-family decontamination. No eval tuning, repaired predictions, or checkpoint promotion.
