The proof (Round {{ prev_round_num }}) is not correct. Following is the compilation error message, where we use <error></error> to signal the position of the error.

{{ error_message }}

Before producing the Lean 4 code that fixes the error, provide a detailed analysis of the error message. Focus on fixing the compilation errors, and try your best to preserve the proof optimization that was previously done. Do not revert to the original unoptimized proof.

{% if use_tactic_style %}
**IMPORTANT: Tactic-Mode Constraint.** The corrected proof **must** remain in **tactic mode** (proof body starts with `:= by` followed by tactic commands). Do **not** convert to term-mode.
{% endif %}

You must wrap the entire Lean 4 theorem and proof in tags like:

```lean4
<your corrected theorem and proof here>```
