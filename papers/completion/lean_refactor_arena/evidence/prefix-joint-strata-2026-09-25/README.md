# Strata joint getVars deletion — 2026-09-25

**Confirmed aggregate trade-off, not a strict-dual improvement:** **168 → 166
tokens**, **1.56265% more raw heartbeats**, **+0.14247 matched-local combined-score
points** against the freshly rechecked incumbent. All 30 native checks verified,
preserving the exact theorem type and the original `propext`, `Quot.sound` axiom set.

Keep both candidates: **166 tokens for the measured aggregate objective**, and
**168 tokens as the faster alternative**. Both remain on the measured Pareto
frontier. No production incumbent was promoted. This is one exposed task, not
an official Arena score, held-out result or whole-corpus improvement.

## Measured result

Task: `CallElimCorrect.extractedOldExprInVars`; sole declared pin: Lean 4.26.0,
Strata commit `451e5f047bafa010d178856db76c00029bfa4d7f`.
Fresh confirmation, three measurements per arm/order:

| Source | Tokens | Raw heartbeats, reference-first | Raw heartbeats, candidate-first |
| --- | ---: | ---: | ---: |
| Original | 222 | 2,607,572–2,607,575 | 2,607,585 each |
| Incumbent | 168 | 790,126 each | 790,139 each |
| Joint deletion | 166 | 802,473 each | 802,486 each |

The candidate costs **12,347 additional raw heartbeats per order**. The smaller
source outweighs this regression under the **predeclared** `aggregate-local-v1`
objective. Conservative descriptive gain stays above **+0.14118 points** after
the frozen 100-raw-unit noise floor and observed ranges. This is not a statistical
confidence bound. Reanalysis with `strict-dual-v1` selects **nothing**, in both
screening and confirmation. Neither policy was changed after seeing results.

Against the original: **25.23% fewer tokens**, **69.23% fewer raw heartbeats**,
**+31.48345 task-local combined-score points**. The local delta is
`100/3 × (token saving / original tokens + raw heartbeat saving / original raw
heartbeats)` within matched orders. [analysis.json](analysis.json) retains exact
rational deltas, the heartbeat regression, strict rejection and both frontier
members. Content hashes identify bytes; they are not proofs or CIDs.

Screening: **12/12 VERIFIED**. Confirmation: **18/18 VERIFIED**. The candidate
passed four screening and six independent confirmation checks. The
[166-token source](composition-0.json) has SHA-256
`bde49db5e4e0faeb439a543c99c3a613e4803b64a122b8215ba5d35300f15707`.
The [168-token faster source](incumbent.json) is retained. These four-field
files are untrusted source nominations, not standalone verification receipts.
The historical 169/170-token sources were not freshly rechecked in this trial.

## Exact intervention and interpretation

The previous trial independently verified two different `getVars` support
deletions from a 170-token source. This trial starts from its confirmed
168-token winner and removes the remaining `Imperative.HasVarsPure.getVars`
entry. Explicit support becomes:

```lean
simp only [extractOldExprVars, List.Subset.empty]
```

Every subsequent case proof, including the repaired left-nested `ite` proof,
and the exact theorem statement stay byte-for-byte unchanged. Offline tests
check equality with removing both entries from the earlier 170-token source
in either correctly indexed order. Equality of edits is not proof authority;
fresh whole-source Lean checks establish their composability here.

The edits compose **logically**, but their heartbeat benefits do not add:
the combination is more expensive than the best single deletion. Removing
explicit simp support does not remove the imported definitions or prevent
Lean from using definitional reduction elsewhere. No general minimality,
causal tactic-cost decomposition or cross-project benefit is established.

The [`simp-prefix-drop-second` profile](../../../../../ARENA_APPEND_TREE.md)
reuses the existing bounded edit and nominates only the second support entry.
It is positional, not a semantic `getVars` recognizer. Missing entries or
unsupported prefixes abstain; no alternative edit is substituted. Existing
admission, exact-context, axiom, scoring, confirmation and resource gates remain
unchanged. No dependency, solver or model was added.

## Frozen protocol and isolation

Plan SHA-256: `009313ad9e369eece32733d9f4403389796c07132ba3f3d8eb122f4a8cca556b`.
[predeclared-plan.json](predeclared-plan.json) equals [plan.json](plan.json).
Ceiling and actual use: **30/30 sequential native processes**: twelve screening
(original, incumbent, candidate × two repeats × both orders), then eighteen
fresh confirmation checks of the same arms. No retries, receipt-cache reuse,
adaptive expansion, API calls, training, builds, downloads or cache deletion.
Launcher wall time: **688.74 seconds**, not a proof execution-speed gain.

Reports, reservations, accounting, console, launch and source binding were
archived byte-for-byte. Both changed code/test files matched the frozen source.
[The audit](audit/summary.md) is **CONSISTENT** with zero new native checks;
it verifies bookkeeping, not independent proof truth. Source binding stayed
**UNCHANGED** before and after execution.

Snapshot: 2,165 files / 58,304,114 bytes; manifest SHA-256
`8515a7b387d38c4c333fd455a26b8cf63724e7a20e5beff348c4fb0bb5b87b92`;
content root `86518d71893fb1acede28147cb1f357cf5d7b251631f75d6cab72c9d7d9a74b6`.
Runtime directory:
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/prefix-joint-strata-xotaxlwh`.
The child used isolated Python imports and inherited only PATH/HOME/LANG/LC_ALL,
disabled external hooks/router flags, and capped-volume TMPDIR. Prepared exact
project/toolchain bindings and the exclusive preparation lock were used.
This is trusted-local execution, not an OS sandbox or distributed execution.

The **50 GB cap** and **100 MB runtime reserve** held. Final free space was
**146,771,968 bytes**; all caches were retained. This is below the 200 MB
pre-snapshot headroom used for these full-copy trials. Another such trial needs
a storage/reduced-snapshot plan first; do not silently delete caches, reduce
the reserve, or increase the user's cap.

## Commands

Plan-only (no Lean/model call):

```bash
env PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
python -m jevops.arena_leaf_pilot \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent papers/completion/lean_refactor_arena/evidence/prefix-deletions-strata-2026-09-25/composition-2.json \
  --profile simp-prefix-drop-second --selection-objective aggregate-local-v1
```

Actual native command, cwd in the snapshot's `source` directory:

```bash
/home/barberb/.local/bin/python -I -B -c \
  'import sys;sys.path.insert(0,sys.argv.pop(1));from jevops.arena_leaf_pilot import main;raise SystemExit(main())' \
  /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/prefix-joint-strata-xotaxlwh/source \
  --problem CallElimCorrect.extractedOldExprInVars --incumbent inputs/incumbent.json \
  --profile simp-prefix-drop-second --selection-objective aggregate-local-v1 \
  --execute --max-processes 30 \
  --snapshot-manifest-sha256 8515a7b387d38c4c333fd455a26b8cf63724e7a20e5beff348c4fb0bb5b87b92 \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --projects inputs/projects.json \
  --elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
  --output /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/prefix-joint-strata-xotaxlwh/experiment
```

New executions require new snapshot/output identities; do not overwrite evidence.
Recorded-result audit command:

```bash
env PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
python -m jevops.arena_report_audit \
  --protocol papers/completion/lean_refactor_arena/evidence/prefix-joint-strata-2026-09-25/selection-protocol.json \
  --report papers/completion/lean_refactor_arena/evidence/prefix-joint-strata-2026-09-25/report.json \
  --output-dir papers/completion/lean_refactor_arena/evidence/prefix-joint-strata-2026-09-25/audit
```

Offline regression before freezing:

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-prefix-joint-tests/cache \
  --junitxml=/tmp/jevops-prefix-joint-tests/regression.xml \
  tests/test_arena_prefix_deletions.py tests/test_arena_append_tree.py \
  tests/test_arena_simp_scope.py tests/test_arena_compositions.py \
  tests/test_arena_leaf_pilot.py tests/test_arena_pareto.py \
  tests/test_arena_aggregate.py tests/test_solver_spans.py -q
```

**725 passed, 3 skipped in 53.31 seconds**; zero reused seals, 679 fresh passes
sealed. This is targeted regression, not a full-repository test run. New cases
cover exact composition in both deletion orders, preservation of case proofs,
current-comparator identity, the 30-call reservation, pre-work plan mutation
rejection and zero-work abstention when the second entry is absent.

Changed implementation: `jevops/arena_leaf_pilot.py` adds one fixed profile;
`tests/test_arena_prefix_deletions.py` adds its contracts. The existing edit
engine and all verification/scoring gates are unchanged. Root README,
`ARENA_APPEND_TREE.md`, solver specialization and safety-plan notes record the
trade-off and both retained candidates. Broader coverage, held-out evaluation,
organizer-worker metric parity and production security remain open.
