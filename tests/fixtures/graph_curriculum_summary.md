# Training-only graph refinement and frozen transfer

Generated from receipts, not fresh verification or an arena result.

Selected solely on training data: `multiscale_online_0.25`. Epochs: 80.
Same examples/pass; batch averages before clipping and has fewer optimizer updates than online.

| Transfer arm | Valid / total | Verified saved tokens | Edit CE | Expected cosine loss |
| --- | --- | --- | --- | --- |
| fixed_graph | 7/7 | 66 | 0.186836 | 0.0894212 |
| frozen_multiscale | 7/7 | 66 | 0.141033 | 0.0734372 |
| last_online_0.15 | 7/7 | 66 | 0.0743832 | 0.0048072 |
| multiscale_online_0.25 | 7/7 | 66 | 0.0753752 | 0.00366055 |
| node_bag | 7/7 | 66 | 0.237913 | 0.136914 |

| Split | Selected / fixed saved tokens | Selected / fixed CE | Selected / fixed cosine loss |
| --- | --- | --- | --- |
| canary | 18 / 18 | 0.0745849 / 0.197306 | 0.00110713 / 0.0670257 |
| holdout | 32 / 32 | 0.0724017 / 0.221161 | 0.00744386 / 0.152719 |
| validation | 16 / 16 | 0.0806257 / 0.124878 | 0.000539026 / 0.0168697 |

Gates: `{"all_splits_pass": true, "baseline_complete_loss_coverage": true, "baseline_savings_nonregression": true, "complete_cost_and_loss_coverage": true, "complete_validity": true, "cross_entropy_nonregression": true, "expected_cosine_loss_nonregression": true}`.
Fresh goal layouts with disjoint family labels and name-insensitive type/proof hashes; shared training rewrite motifs.
Not mathematical-family decontamination. No eval tuning, repaired predictions, or checkpoint promotion.
