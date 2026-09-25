Your task is to analyze a given Lean 4 proof from a research level project and create a structured plan for optimizing and shortening it, while maintaining the correctness.

## Instructions

Analyze the proof and identify regions that can be optimized and simplified. For each optimization opportunity:

{% if use_tactic_style %}
**Tactic-Mode Constraint:** The proof is written in Lean 4 **tactic mode** (the proof body starts with `:= by` followed by tactic commands). All optimization plans **must** preserve tactic-mode style. Do not propose converting the proof to term-mode.
{% endif %}

1. **Identify the line range** (1-indexed) of the region to optimize. The beginning of the theorem statement is line 1.
2. **Provide a title**: a short descriptive name that summarizes your strategy.
3. **Provide potential reduction**: state the potential reduction from this strategy (high, medium, or low)
4. **Determine an optimization strategy**: describe your detailed plan on how you can optimize the region, including descriptions of the code transformations you plan to do and the rationale behind the strategy. You do not need to provide concrete code transformations, just a detailed plan is enough.

## Inputs

1. You will receive a correct Lean 4 statement and proof source code.
2. Its elaborated signature.
3. Its doc string from the source if it exists in the source.
4. All the dependencies used in the statement and proof from the same Lean 4 project it originated from. Mathlib 4 dependencies are not included for brevity. If there are no dependencies from the Lean 4 project that the proof comes from (this means the proof only depends on Mathlib 4), then no dependencies will be provided.

## Output Format

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

## Example:

Input theorem:
```lean4
theorem verbose_proof [AddMonoidWithOne G] [AddMonoid H] [AddConstMapClass F G H 1 b]
    (f : F) (n : ℕ) [n.AtLeastTwo] :
    f (ofNat(n)) = f 0 + (ofNat(n) : ℕ) • b :=
by
  classical
  calc
    f (OfNat.ofNat n)
        = f ((n : G)) := by
          rfl
    _ = f 0 + (n : ℕ) • b := by
          simpa using (map_nat' (f := f) (n := n))
    _ = f 0 + (OfNat.ofNat n : ℕ) • b := by
          rfl
```

Output plans:
```json
[
  {
    "line_start": 5,
    "line_end": 13,
    "title": "Collapse calc chain into one `simpa` from `map_nat'`",
    "reduction": "high",
    "description": "**Strategy:** The entire proof is a verbose expansion of the lemma `map_nat'`. The intermediate `calc` steps merely handle `OfNat` vs `Nat` coercions, which are definitionally equal in Lean. The whole block can be replaced by applying the lemma directly. **How to shorten:** - Replace the entire `by ...` block with `map_nat' f n`. **Rationale:** `map_nat'` provides the exact equality required. The type checker handles the definitional unfolding of `ofNat(n)` to `n` automatically, rendering the `calc` block redundant."
  },
  {
    "line_start": 5,
    "line_end": 5,
    "title": "Remove unused `classical`",
    "reduction": "low",
    "description": "**Strategy:** The `classical` tactic is included but likely unused. The proof relies on arithmetic properties and `map_nat'`, which typically do not require classical logic (decidability of propositions) for this specific algebraic structure. **How to shorten:** - Delete line 5 (`classical`). **Rationale:** `classical` indiscriminately adds the Law of Excluded Middle to the local context. Since `Nat` equality is already decidable, this is overkill. Removing it ensures the proof uses minimal axioms and remains constructive (computable), avoiding \"logical pollution.\""
  },
  {
    "line_start": 6,
    "line_end": 13,
    "title": "Simplify `calc` steps",
    "reduction": "medium",
    "description": "**Strategy:** If the `calc` block is desired for exposition, the tactic usage within it is unnecessarily heavy. `simpa` is slow and `rfl` works for the definitional steps. The middle step can be closed with `exact` instead of `simpa`. **How to shorten:** - Replace `simpa using ...` in L11 with `exact map_nat' f n`. - Collapse the `calc` block if possible, or verify if the `rfl` steps are even needed (usually `map_nat'` matches the goal directly without manual unfolding). **Rationale:** The intermediate steps are \"syntactic noise\"-they do not prove new facts, but only confirm definitions that the compiler already knows. Removing them makes the proof strictly shorter and easier to read. Also, `simpa using ...` term is longer and slower than using `exact ...`, while achieving the same result."
  },
  {
    "line_start": 11,
    "line_end": 11,
    "title": "Remove named arguments",
    "reduction": "low",
    "description": "**Strategy:** The named arguments `(f := f)` and `(n := n)` are likely redundant if `f` and `n` are explicit arguments in `map_nat'`, which is standard. **How to shorten:** - Change `map_nat' (f := f) (n := n)` to `map_nat' f n`. **Rationale:** Positional arguments are idiomatic in Lean 4 when parameters are explicit."
  }
]
```

Here is the proof to optimize:
```lean4
{{ current_proof }}
```

{% if signature %}
Theorem's elaborated signature:
{{ signature }}
{% endif %}

{% if informalization %}
Theorem's documentation:
{{ informalization }}
{% endif %}

{% if dependencies %}
Information about dependencies used in the proof:
{{ dependencies }}
{% endif %}

Now analyze the proof and generate your optimization plans.
