A previous optimization plan has been executed, and the proof has been shortened. Your task is to review the updated proof and the optimization process to update the plan for further optimization and simplification.

## Instructions

- You will be given a partially optimized proof, that has been shortened compared to the previous version of the proof (previous proof is also provided).
- You will also be given the previous plans for optimizing and shortening the previous proof, as well as the status of each plan (either completed, failed, or pending).
- You must carefully analyze the current partially optimized proof, the previous plans, and their execution status, to provide an updated version of the plans to better simplify the current proof
- Since the proof structure might have changed, do NOT include plans from the previous plan that are no longer applicable (e.g., the targeted code no longer exists, or has failed status and you are not sure how to modify it).

{% if use_tactic_style %}
**Tactic-Mode Constraint:** The proof is written in Lean 4 **tactic mode** (the proof body starts with `:= by` followed by tactic commands). All optimization plans **must** preserve tactic-mode style. Do not propose converting the proof to term-mode.
{% endif %}
- Previous plans with pending status should be carefully analyzed, and updated if needed (line numbers, strategy descriptions) based on the current proof.
- If you identify new opportunity for shortening the current proof that did not exist in the previous proof plan, you can add it into the updated plan.


{% if previous_proof %}
## Previous Proof (Before Optimization)
The proof before the successful optimization was:
```lean4
{{ previous_proof }}
```
{% endif %}

{% if signature %}
Theorem's elaborated signature:
{{ signature }}
{% endif %}

{% if informalization %}
Theorem's documentation:
{{ informalization }}
{% endif %}

{% if dependencies %}
Information about the dependencies used in the original proof. These are from the same Lean 4 project it originated from; Mathlib 4 dependencies are not included for brevity. Some of these may no longer be used in the current partially optimized proof, but they are provided for your understanding.
{{ dependencies }}
{% endif %}

## Current Partially Optimized Proof
The current proof after partial optimization:
```lean4
{{ current_proof }}
```

{% if last_round_plans %}
## Previous Round's Plans and Outcomes
The following are the plans from the previous round and their status.
Plans marked [COMPLETED] were executed successfully and led to shortening of the proof, and this triggered this replan since proof code is changed.
Plans marked [FAILED] encountered serious compilation errors that cannot be resolved. Consider skipping these in your updated plan.
Plans marked [PENDING] were not executed (replan was triggered before reaching them).

{{ last_round_plans }}
{% endif %}

Output the plans using the following JSON format, wrapped in a single ```json ``` tags.
Ensure the output is valid JSON. Specifically, make sure to escape any double quotes or backslashes within the string values (e.g., use `\"` for quotes and `\\` for backslashes).

```json
[
  {
    "line_start": X,
    "line_end": Y,
    "title": "the strategy name",
    "reduction": "high, medium, or low",
    "description": "Detailed description of the optimization strategy to apply at this region of proof, describing the strategy, how to shorten the region, and the rationale behind the strategy."
  }
]
```

Rules about the ordering of the output plans:

1) Sort plans primarily from top to bottom of the proof (increasing line numbers).
2) Overlaps of optimization regions are allowed. If two plans overlap in location, put the plan with the MOST significant potential reduction first.
3) If two plans have the same overlap + same potential impact, keep top-to-bottom ordering.

Now, provide your updated optimization plans.
