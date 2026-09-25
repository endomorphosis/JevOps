# Frozen scoped-training transfer control

Outcome: failed; checkpoint unchanged; no promotion.

Same frozen grammar and one raw candidate check per arm/source; not wall-time or training-compute matched.
Token-length logits = negative source tokens, temperature 1; loss smoothing 0.02 fixed before evaluation.

| Arm | Valid / cases | Cost-safe | Loss coverage | Verified saved tokens | Edit CE | Expected cosine loss |
| --- | --- | --- | --- | --- | --- | --- |
| learned | 6/6 | 6 | 6 | 42 | 0.046776739 | 0.0039955423 |
| fixed_graph | 6/6 | 6 | 6 | 42 | 0.080824738 | 0.023903522 |
| token_length | 6/6 | 6 | 6 | 42 | 0.12223576 | 0.013140275 |

Failed comparison gates:

- canary/token_length: expected_cosine_loss_nonregression
- holdout/token_length: expected_cosine_loss_nonregression

Failed global gates: all_splits_pass.

Native compiler calls (deduplicated): 11.
All raw predictions were committed before labels. Missing/invalid/unreachable labels fail coverage, not identity labels.
Named validation/canary/holdout partitions are shared-motif transfer controls, not decontaminated mathematical families.
CE/cosine are edit-policy diagnostics, not reconstruction loss or semantic equivalence.
No training, repair, reference retuning, checkpoint promotion or arena score.
