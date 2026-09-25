# Joint simplifier / append-tree experiment

This is an opt-in extension of the existing composition and leaf pilot, not a
new solver or proof admission path. The fixed `simp-prefix-append-tree` profile
nominates two drafts from a supplied incumbent:

1. Delete exactly `List.append_assoc` from a bounded goal-only `simp only`
   induction prefix; leave the continuation unchanged as a control.
2. Perform that deletion and reconstruct one exact right-nested three-leaf
   `List.Subset.app` proof as a left-nested tree, preserving the captured leaf
   hypotheses and their `assumption` discharges.

The source definitions in the prepared Strata revision use left-associated
append for the conditional case on both sides. Historical deletion-only
failure showed a single-leaf hypothesis being applied to a pair-of-lists goal.
This motivates the joint edit; it does not establish that it compiles or costs
less. A prefix edit can affect all branches. Every candidate therefore needs
fresh **whole-proof** checking against the exact statement, project, pin and
axiom policy. Python layout recognition is not Lean elaboration.

The deletion matcher abstains on changed scope, multiple intro names, duplicate
normalization entries, unsupported expressions, comments and ambiguous layout.
It reuses the source-bound `SolverEdit` mechanism. The tree matcher reuses the
existing exact subtree recognizer, keeps the statement and other branches, and
allows no token growth. Neither operation admits evidence. If the second step
abstains, the joint path emits no partially repaired draft. The separately
declared deletion control may still be emitted and fail native checking.

Plan-only command (offline):

```bash
PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
python -m jevops.arena_leaf_pilot \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent papers/completion/lean_refactor_arena/evidence/simp-scope-strata-2026-09-25/composition-0.json \
  --profile simp-prefix-append-tree --selection-objective aggregate-local-v1
```

For this exposed task, the original has 222 tokens, the aggregate incumbent
172, and both new drafts 170. The separate historical 169-token baseline is not
the comparator and is not rechecked in this trial. Selection is explicitly
`aggregate-local-v1`; the existing default remains `strict-dual-v1`.

The frozen ceiling is 34 sequential native processes: 16 screening (four arms,
two repetitions, both branch orders), and at most 18 fresh confirmation checks
(original, incumbent, one fixed winner; three repetitions, both orders).
The existing 100-raw-heartbeat noise floor plus observed ranges applies.
No retries, post-result candidate expansion, automatic promotion, models,
builds, downloads or cache deletion. The read-only source snapshot, prepared
dependency bindings, exclusive preparation lock, and 50 GB volume cap are
required for execution. Results are task-local, not an official Arena score or
held-out evaluation. A failed control remains a failed observation.

## Observed first trial

The [completed Strata trial](papers/completion/lean_refactor_arena/evidence/append-tree-strata-2026-09-25/README.md)
confirmed the joint repair: 172 → 170 tokens, 3.61223% fewer raw heartbeats,
and +0.72983 task-local combined-score points. Deletion alone failed all four
screening checks. The joint draft passed four screening and six fresh
confirmation checks; all 18 confirmation checks including controls verified
with unchanged axioms. Total: 34 native processes; 659 offline tests passed,
three skipped. The snapshot stayed unchanged and the bookkeeping audit was
consistent. The separate historical 169-token baseline was not rechecked and
remains shorter. No official score or production promotion is claimed.

## Remaining support: bounded single deletions

The opt-in `simp-prefix-single-deletions` profile nominates each single-entry
deletion from a goal-only induction prefix containing one to four distinct
support entries. Every path starts from the same exact seed; successful edits
are not automatically chained. The existing source-bound prefix recognizer is
shared with append-normalization deletion, whose earlier behavior is preserved.
Longer lists abstain entirely instead of silently testing just their first four
entries. Empty, duplicate, unsupported or differently scoped prefixes abstain.
Only the support span changes; subsequent case proofs are retained byte-for-byte.

```bash
PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
python -m jevops.arena_leaf_pilot \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent papers/completion/lean_refactor_arena/evidence/append-tree-strata-2026-09-25/composition-1.json \
  --profile simp-prefix-single-deletions --selection-objective aggregate-local-v1
```

This is plan-only. For the 170-token repaired source, the four fixed drafts
remove, respectively, `extractOldExprVars`, `Imperative.HasVarsPure.getVars`,
`Lambda.LExpr.LExpr.getVars`, or `List.Subset.empty`. Each has 168 tokens.
The exact ceiling is 42 sequential native checks: 24 screening (original,
incumbent, four drafts × two repeats × both orders), then at most 18 fresh
confirmation checks for only the fixed winner. The same proof, axiom, storage,
snapshot, noise-margin and no-retry policies apply. There are no models/builds.

Rejection of every one-entry deletion would only exclude these four exact
sources under this checker and pin. It would not establish global minimality,
exclude multi-entry deletions, or show that replacement lemmas or dependent
case repairs cannot help. Historical evidence never substitutes for a fresh
control or candidate check.

The [completed single-deletion trial](papers/completion/lean_refactor_arena/evidence/prefix-deletions-strata-2026-09-25/README.md)
confirmed removal of `Lambda.LExpr.LExpr.getVars`: **170 → 168 tokens**,
**11.87453% fewer raw heartbeats**, **+1.66129 local combined-score points**.
Removing `Imperative.HasVarsPure.getVars` also qualified in screening but cost
more than the winner; it was not independently confirmed. The other two
deletions failed all four checks each. Total: 42 native checks, 34 verified /
eight rejected, including all 18 confirmation checks verified with unchanged
axioms. Offline regression: 716 passed / three skipped. Snapshot and audit
passed. That trial did not test the two individually valid deletions together.

## Predeclared second-entry follow-up

`simp-prefix-drop-second` reuses the same bounded edit and nominates **only the
second support entry** (zero-based index one). It is a positional profile, not
a semantic `getVars` recognizer. It abstains if the entry is absent or the
existing prefix/list restrictions fail; it does not switch to another edit.

On the confirmed 168-token source below, this deletes
`Imperative.HasVarsPure.getVars`. The resulting 166-token source is byte-identical
to removing both `getVars` entries from the earlier 170-token source, in either
correctly indexed order. This equality is tested offline, not treated as proof
that the edits compose. Every case proof and the exact statement are preserved.

```bash
PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
python -m jevops.arena_leaf_pilot \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent papers/completion/lean_refactor_arena/evidence/prefix-deletions-strata-2026-09-25/composition-2.json \
  --profile simp-prefix-drop-second --selection-objective aggregate-local-v1
```

This is plan-only. The full ceiling is 30 sequential native checks: twelve
screening (original, current 168-token incumbent, one fixed draft × two repeats
× both orders), and at most eighteen fresh confirmation checks of those same
arms. Prior receipts and the older 170-token comparator are not substituted for
fresh controls. No other deletion or automatic follow-on search is included.
All existing proof, axiom, context, noise, snapshot and resource gates apply.

The [completed joint trial](papers/completion/lean_refactor_arena/evidence/prefix-joint-strata-2026-09-25/README.md)
found a **trade-off**: 168 → 166 tokens, **1.56265% more raw heartbeats**, and
**+0.14247 local combined-score points** under the predeclared aggregate
objective. All 30 native checks verified with unchanged axioms; 725 offline
tests passed / three skipped. Strict-dual reanalysis rejects the edit: retain
the 168-token source as the faster alternative alongside the 166-token
aggregate candidate. Both are on the Pareto frontier. Snapshot and audit passed;
no official score or production promotion. Final free capped space was about
147 MB, below the 200 MB pre-snapshot headroom for another full-copy trial.
