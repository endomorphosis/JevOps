You are given a correct Lean 4 proof of a mathmatical theorem from real libraries, it’s elaborated signature, and dependencies used in the theorem. Your goal is to simplify and clean up the proof, making it shorter while ensuring it is still correct. Focus on structural optimization, and come up smarter ways to write the proof to make it shorter and still correct.
Here is the original theorem and proof:
```lean4
{{ current_proof }}```

Theorem’s elaborated signature:
{{ signature }}

Theorem's doc string:
{{ informalization }}

Information about the dependencies used in the original proof. Note, the provided dependencies are from the same Lean 4 project that the current theorem is in. Mathlib 4 dependencies are not included for brevity.
{{ dependencies }}

{% if use_tactic_style %}
## Tactic-Mode Constraint

**IMPORTANT:** The optimized proof **must** be written in **tactic mode**. In Lean 4, tactic-mode proofs begin with `:= by` after the theorem signature, followed by a sequence of tactic commands to incrementally transform and solve a goal state.

You **must not** convert the proof to term-mode. The proof body must start with `:= by`.
{% endif %}

Now, provide the complete code, including the original theorem statement(not the elaborated signature) and your simplified proof. Do NOT modify the original theorem statement. You must wrap the entire Lean 4 theorem and proof in tags like:

```lean4
<your optimized theorem and proof here>```
