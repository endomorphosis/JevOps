# Native-rejection training: learning-rate comparison

Generated from saved native training observations, not fresh verification or held-out performance.
Same eight-case protocol (or caller-supplied matched rows), initial graph weights, grammar and updates; only learning rate differs between runs.

| Learning rate | Arm | Acceptable / cases | Correct | Verified saved tokens | CE | Expected cosine | Rejected probability |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.05 | ce_cosine | 8/8 | 6 | 72 | 0.71025661 | 0.25535315 | 0.020319737 |
| 0.05 | ce_cosine_rejection | 8/8 | 6 | 72 | 0.74807563 | 0.25511352 | 0.017194392 |
| 0.05 | fixed_graph | 8/8 | 6 | 72 | 0.35237641 | 0.21630792 | 0.047128038 |
| 0.05 | token_length | 5/8 | 5 | 44 | 0.67996166 | 0.35123442 | 0.27414362 |
| 0.15 | ce_cosine | 8/8 | 6 | 72 | 0.70704993 | 0.25162293 | 0.01779957 |
| 0.15 | ce_cosine_rejection | 8/8 | 6 | 72 | 0.74544547 | 0.25176612 | 0.015037365 |
| 0.15 | fixed_graph | 8/8 | 8 | 74 | 0.1401852 | 0.085326372 | 0.037684524 |
| 0.15 | token_length | 5/8 | 5 | 44 | 0.67996166 | 0.35123442 | 0.27414362 |
| 0.25 | ce_cosine | 8/8 | 6 | 72 | 0.69340257 | 0.24910299 | 0.016294302 |
| 0.25 | ce_cosine_rejection | 8/8 | 6 | 72 | 0.7320819 | 0.24960514 | 0.013742374 |
| 0.25 | fixed_graph | 8/8 | 8 | 74 | 0.099879177 | 0.045412838 | 0.019929256 |
| 0.25 | token_length | 5/8 | 5 | 44 | 0.67996166 | 0.35123442 | 0.27414362 |

Best graph on training criteria: ce_cosine at LR 0.25.
Best trained control: fixed_graph at LR 0.25.
Unknown failures are not negative labels. CE/cosine and smoothing are unchanged by the auxiliary penalty.
Lower rejected probability alone is not success: validity, shortest admitted labels and separate losses remain visible.
The old frozen-transfer failure is not replaced by these training results. No promotion, arena score, or global-minimality claim.
