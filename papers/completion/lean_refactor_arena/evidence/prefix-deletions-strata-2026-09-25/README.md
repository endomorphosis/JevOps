# Strata remaining-prefix single deletions — 2026-09-25

**`CONFIRMED_LOCAL_IMPROVEMENT`**: **170 → 168 tokens**, **11.87453% fewer raw
heartbeats**, **+1.66129 matched-local combined-score points** against the freshly
rechecked aggregate incumbent. The selected edit removes only
`Lambda.LExpr.LExpr.getVars` from explicit simplifier support, preserving every
case proof, including the previously repaired left-nested `ite` proof.

This is one exposed Arena task, not an official Arena score, whole-corpus gain,
held-out result or production promotion. No model, build or download was used.

## Results

Task: `CallElimCorrect.extractedOldExprInVars`; sole declared pin: Lean 4.26.0,
Strata commit `451e5f047bafa010d178856db76c00029bfa4d7f`.
Fresh confirmation, three measurements per arm/order:

| Source | Tokens | Raw heartbeats, reference-first | Raw heartbeats, candidate-first |
| --- | ---: | ---: | ---: |
| Original | 222 | 2,607,572–2,607,573 | 2,607,585 each |
| Incumbent | 170 | 896,593 each | 896,606 each |
| Selected deletion | 168 | 790,126 each | 790,139 each |

The saving is **106,467 raw heartbeats per order** over the incumbent. The
conservative descriptive combined gain stays above **+1.66001 points** after
the frozen 100-raw-unit noise floor and observed ranges. This is not a
statistical confidence bound. Against the fresh original: **24.32% fewer
tokens**, **69.70% fewer raw heartbeats**, **+31.34098 local score points**.
The local delta is `100/3 × (token saving / original tokens + raw heartbeat
saving / original raw heartbeats)`, within matched orders. [analysis.json](analysis.json)
retains exact rational deltas; percentages are descriptive means.

All four predeclared drafts were 168 tokens:

| Draft | Deleted support entry | Screening result |
| --- | --- | --- |
| `composition-0` | `extractOldExprVars` | Four rejections: unsolved `const`, `op`, `bvar`, `fvar` cases |
| `composition-1` | `Imperative.HasVarsPure.getVars` | Four verified; 858,212 / 858,225 raw heartbeats |
| `composition-2` | `Lambda.LExpr.LExpr.getVars` | Four verified; 790,126 / 790,139 raw heartbeats; selected |
| `composition-3` | `List.Subset.empty` | Four rejections: empty-list subset goals left unsolved |

The runner-up improved screening raw heartbeats by **4.28%** and local score
by **+0.79093 points** against the incumbent, but is **screening-only**, not
independently confirmed. Both valid drafts qualified; the faster one dominated
at equal token count. The two failing drafts have no admitted cost result.
Their failures are preserved, not treated as proof that their statements are false.

Total screening: **16 VERIFIED / 8 REJECTED**. Confirmation: **18/18 VERIFIED**.
The winner passed four screening and six fresh confirmation checks. All admitted
arms retained exactly `propext` and `Quot.sound`, with the exact target type.
Reanalysis also passes strict-dual against the supplied **170-token** incumbent.
The new candidate is shorter than the historical 169-token source, but that
source was not freshly rechecked here; no paired cost comparison against it is
claimed. No authoritative production incumbent was changed.

The new aggregate development candidate is [composition-2.json](composition-2.json),
source SHA-256 `0fdfaac310c1a2e306010b34d6a54287259204439b9441414f9dc4ebac5b4954`.
All four draft files and [incumbent.json](incumbent.json) remain four-field,
untrusted source nominations. They are not verification receipts.

## Implemented profile and frozen protocol

[`simp-prefix-single-deletions`](../../../../../ARENA_APPEND_TREE.md) reuses the
composition/leaf pilot. Each path deletes one indexed entry from the **same**
seed, not from a previously successful deletion. The existing bounded goal-only
prefix recognizer and source-bound `SolverEdit` are reused. One to four distinct
support entries are supported; longer or duplicate lists abstain rather than
silently truncating the neighborhood. Other scopes and unsupported layout
abstain. The earlier named append-associativity deletion retains its behavior.

The static matcher is not a Lean parser or proof authority. Omission from explicit
simp support does not mean the underlying imported definition is unused; Lean
can still use definitional reduction. Whole-proof checks, exact dependencies and
the existing axiom gate establish admissibility, not the source edit itself.

Explicit objective: `aggregate-local-v1`; the default stays `strict-dual-v1`.
Frozen ceiling and actual use: **42/42 sequential native processes**: 24 screening
(original, incumbent, four drafts × two repeats × both orders), then 18 fresh
confirmation checks of original, incumbent and only the fixed winner. No retries,
receipt-cache reuse, adaptive expansion, training or promotion. Launcher wall
time was **944.43 seconds**, not a measured end-to-end proof speedup.

Plan SHA-256: `fddeeb3ca2874af0183582e4c4f9846f048e73019a342306d458b477812093ca`.
[predeclared-plan.json](predeclared-plan.json) equals [plan.json](plan.json).
Runtime reports, accounting, reservations, console, launch and source binding
were archived byte-for-byte. All three changed code/test files matched the
frozen source at archiving. [The audit](audit/summary.md) is **CONSISTENT**, with
zero fresh native checks: it checks bookkeeping, not independent proof truth.
The source binding is **UNCHANGED**. SHA-256 content hashes are not proofs or CIDs.

## Commands and isolation

Plan-only command (no Lean or model call):

```bash
env PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
python -m jevops.arena_leaf_pilot \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent papers/completion/lean_refactor_arena/evidence/append-tree-strata-2026-09-25/composition-1.json \
  --profile simp-prefix-single-deletions --selection-objective aggregate-local-v1
```

Read-only snapshot: 2,142 files / 57,421,454 bytes; manifest SHA-256
`dccd5dc566a637ca4a87336447436135357200547a0a45850a6c3b920a9037ee`;
content root `3d8ef736d8b3cdf7896e88afef3b241d232167c53833321dde1c5cec1106e3ec`.
Runtime directory:
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/prefix-deletions-strata-a0mitids`.

Actual native command, cwd in its `source` directory:

```bash
/home/barberb/.local/bin/python -I -B -c \
  'import sys;sys.path.insert(0,sys.argv.pop(1));from jevops.arena_leaf_pilot import main;raise SystemExit(main())' \
  /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/prefix-deletions-strata-a0mitids/source \
  --problem CallElimCorrect.extractedOldExprInVars --incumbent inputs/incumbent.json \
  --profile simp-prefix-single-deletions --selection-objective aggregate-local-v1 \
  --execute --max-processes 42 \
  --snapshot-manifest-sha256 dccd5dc566a637ca4a87336447436135357200547a0a45850a6c3b920a9037ee \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --projects inputs/projects.json \
  --elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
  --output /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/prefix-deletions-strata-a0mitids/experiment
```

New runs need new snapshot/output identities; do not overwrite this archive.
The child inherited only PATH/HOME/LANG/LC_ALL plus disabled external hooks/router
flags and capped-volume TMPDIR, with isolated Python imports. Measurements used
existing dependency/toolchain caches, exact project bindings and the exclusive
preparation lock. This is trusted-local execution, not an OS sandbox. The 50 GB
cap and 100 MB runtime reserve were respected; final free space was
**211,943,424 bytes**. No caches were deleted.

Recorded-result audit:

```bash
env PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
python -m jevops.arena_report_audit \
  --protocol papers/completion/lean_refactor_arena/evidence/prefix-deletions-strata-2026-09-25/selection-protocol.json \
  --report papers/completion/lean_refactor_arena/evidence/prefix-deletions-strata-2026-09-25/report.json \
  --output-dir papers/completion/lean_refactor_arena/evidence/prefix-deletions-strata-2026-09-25/audit
```

## Offline regression and changed files

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-prefix-deletions-tests/cache \
  --junitxml=/tmp/jevops-prefix-deletions-tests/regression.xml \
  tests/test_arena_prefix_deletions.py tests/test_arena_append_tree.py \
  tests/test_arena_simp_scope.py tests/test_arena_compositions.py \
  tests/test_arena_leaf_pilot.py tests/test_arena_pareto.py \
  tests/test_arena_aggregate.py tests/test_solver_spans.py -q
```

**716 passed, 3 skipped in 51.90 seconds**, before freezing; zero reused seals,
670 fresh passes sealed. This is targeted offline regression, not a full-repository
run or native proof evidence. There were no failures in this regression run.

- `jevops/arena_compositions.py`: shared prefix recognizer, bounded indexed
  deletions, existing named-deletion compatibility, four fixed composition rules.
- `jevops/arena_leaf_pilot.py`: opt-in fixed four-path profile; existing proof,
  cost, confirmation, snapshot and resource gates unchanged.
- `tests/test_arena_prefix_deletions.py`: complete one-to-four-entry nominations,
  bounds, abstention, exact preservation, independent paths, deduplication,
  legacy compatibility, correct comparator/reservation and pre-work rejection.
- `ARENA_APPEND_TREE.md`, root README, solver specialization and safety plan:
  contract, measured outcomes and current candidate identity.

Next: a separately frozen trial could combine the two individually valid
deletions from the same 170-token source, with fresh checks against this new
168-token candidate. This composition was not tested here: separate success
does not guarantee combined correctness or lower cost. Broad/held-out task
coverage, organizer-worker metric parity and production security gates remain
open. The four single deletions do not establish global support minimality.
