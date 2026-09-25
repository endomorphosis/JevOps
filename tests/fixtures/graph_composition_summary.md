# Checked graph edit composition

Generated from saved receipts; not fresh verification or an arena score.

Training-selected model: `multiscale_online_0.25`; 80 passes over 8 adjacent training pairs.
Grammar: 4 shared templates. Composition budget: 3 edits.

| Arm | Raw valid / total | Failed paths | Verified saved tokens | Edit CE | Expected cosine loss |
| --- | --- | --- | --- | --- | --- |
| selected_one | 6/6 | 0 | 90 | 0.0651843 | 0.0021204 |
| selected_composed | 6/6 | 0 | 114 | 0.0651843 | 0.0021204 |
| fixed_one | 6/6 | 0 | 90 | 0.0897166 | 0.00883677 |
| fixed_composed | 6/6 | 0 | 114 | 0.0897166 | 0.00883677 |
| frozen_composed | 6/6 | 0 | 114 | 0.0709026 | 0.00461048 |

| Split | Selected / fixed composed saved tokens | Selected / fixed CE | Selected / fixed cosine loss |
| --- | --- | --- | --- |
| validation | 38 / 38 | 0.0647375 / 0.114114 | 0.00308148 / 0.0165628 |
| canary | 38 / 38 | 0.0648052 / 0.0765368 | 0.00166922 / 0.0050333 |
| holdout | 38 / 38 | 0.0660103 / 0.0784992 | 0.00161051 / 0.00491421 |

Gates: `{"all_splits_pass": true, "baseline_complete_loss_coverage": true, "baseline_savings_nonregression": true, "complete_cost_and_loss_coverage": true, "complete_validity": true, "cross_entropy_nonregression": true, "expected_cosine_loss_nonregression": true}`.
CE/cosine use complete teacher-forced adjacent labels, averaged per theorem, not final-output reconstruction or on-policy sequence loss.
One/composed arms reuse identical weights and loss measurements; only their rollout edit budgets differ.
Invalid raw edits end the path, earn zero saved-token credit, and are not repaired using teachers or alternate candidates.
Shared motifs, not semantic decontamination, global minimality, or evidence for checkpoint promotion.
