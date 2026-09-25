# Contributing: harvesting long Lean proofs


We are looking for proofs that are long enough to leave room for shortening, ideally expensive to compile
(high heartbeat), and whose statement exists unchanged across several toolchains, so they can
be replayed and compared across Lean versions.

## 1. Long

Ideally well over 30 lines for the whole declaration (statement + proof). Existing records run
55–209 lines. Short proofs leave no slack — there is nothing to shorten, so nothing to measure.

Note we don't rank by line count: we run the proof body through a tokenizer and count **tokens**
(comments and blank lines stripped), so padding with whitespace and comments doesn't help.
Existing records run 222–1906 tokens.

## 2. Expensive to compile

Prefer proofs that burn **heartbeats**. A proof that costs real elaboration time has real search
in it; a cheap one is usually plumbing, and compile cost gives us a second axis to improve
besides length. If you can build the project, use `#count_heartbeats` (under
`set_option Elab.async false`) to find the worst offenders.

## 3. Unchanged across toolchains

Pick a few toolchain snapshots for the project. The **exact declaration text must appear
verbatim in a `.lean` file at every one of them** (same bytes, not "an equivalent statement").

Why this matters: tactics, `simp` sets, and library lemmas shift between Lean releases, so a
proof that works at one version may not at another. Holding the statement fixed across versions
is what makes the comparison meaningful — any difference in the replayed proof is attributable
to the toolchain, not to the theorem having changed. That lets us check whether a shortened
proof is genuinely robust or just tuned to one snapshot.

---

## What to send

Email ([mike_lu@sfu.ca](mailto:mike_lu@sfu.ca)):

- the fully-qualified declaration name
- the path to the `.lean` file it lives in
- the commits it's verified at (for cross-version testing)
- the GitHub project URL

Thank you for helping with this — every contribution is much appreciated.
