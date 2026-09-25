# Strata append-normalization / tree-repair trial — 2026-09-25

**`CONFIRMED_LOCAL_IMPROVEMENT`**: **172 → 170 tokens**, **3.61223% fewer
raw heartbeats**, and **+0.72983 matched-local combined-score points** against
the freshly rechecked aggregate incumbent. Removing append normalization alone
failed; removing it together with the dependent proof-tree repair succeeded.
This is one exposed Arena task, not an official or whole-corpus score.

## Results

Task: `CallElimCorrect.extractedOldExprInVars`. Sole declared pin: Lean 4.26.0,
Strata commit `451e5f047bafa010d178856db76c00029bfa4d7f`.
Fresh confirmation, three measurements per arm/order:

| Source | Tokens | Raw heartbeats, reference-first | Raw heartbeats, candidate-first |
| --- | ---: | ---: | ---: |
| Original | 222 | 2,607,572 each | 2,607,585 each |
| Aggregate incumbent | 172 | 930,194 each | 930,207 each |
| Joint repair | 170 | 896,593 each | 896,606 each |

Saving: **33,601 raw heartbeats per order** against the incumbent. The
conservative descriptive combined gain remains above **+0.72855 points** after
the predeclared 100-raw-unit noise floor and observed ranges; this is not a
statistical confidence interval. Versus the fresh original: **23.42% fewer
tokens**, **65.62% fewer raw heartbeats**, **+29.67968 local score points**.
The local delta is `100/3 × (token saving / original tokens + raw heartbeat
saving / original raw heartbeats)`, calculated within each matched order.
Exact rational deltas are retained in [analysis.json](analysis.json).

Screening: **12 VERIFIED, 4 REJECTED**. Every rejection was the deletion-only
control, in both orders and repetitions. Its diagnostics show `cih` being
applied to a pair-of-lists subset goal, followed by an append split applied to
a single-list goal. It has no admitted cost result. It is not a smaller valid
proof and its failures are not discarded from accounting.

Confirmation: **18/18 VERIFIED**; the candidate itself passed four screening
and six independent confirmation checks. All admitted arms had exactly
`propext` and `Quot.sound`, preserving the original axiom set and target type.
Reanalysis of the same observations also passes strict-dual against the supplied
**172-token** incumbent. This is not a strict-dual win over the separate
historical **169-token** source, which was not rechecked and remains shorter.

The new aggregate development candidate is [composition-1.json](composition-1.json),
SHA-256 `7d99ba8b2660e866895a7666469e609dbfb5cd51118e72404f12782d5dabd453`.
[composition-0.json](composition-0.json) is the rejected deletion-only control;
[incumbent.json](incumbent.json) is the 172-token input. These four-field files
are untrusted source nominations, not proof receipts. No production incumbent
store was updated, and no training, model call or official submission occurred.

## Intervention and frozen protocol

The implemented [profile](../../../../../ARENA_APPEND_TREE.md) reuses the
composition and leaf-pilot modules. The two fixed paths are:

1. `simp_prefix_no_append_assoc`.
2. `simp_prefix_no_append_assoc → subset_triple_left_nested`.

The first deletes one support entry from the goal-only induction prefix. The
second additionally changes only the recognized three-leaf `ite` proof tree,
using the same captured hypotheses and existing append/subset lemmas. Other
case proofs and the exact theorem statement remain unchanged. This makes the
proof match the left-associated append in the source definitions without first
normalizing it to a right-associated form. Layout matching is neither a Lean
parser nor a certificate; whole-proof checks establish admissibility.

Both drafts were 170 tokens before execution. The selector was explicitly
`aggregate-local-v1`; the default remains `strict-dual-v1`. Frozen ceiling:
**34 sequential native processes**, 16 screening plus 18 fresh confirmation
for only the fixed screening winner. No retries, post-result expansion, receipt
cache reuse, builds, downloads or cache deletion. Actual use was **34/34**.
Launcher wall time: **767.85 seconds**, not a theorem execution-speed metric.

Plan SHA-256: `edb17f16c3b072d9908f67f535060c878801b50a4cc8db63059ed3c0e992ecd8`.
The [predeclared plan](predeclared-plan.json) equals the [executed plan](plan.json).
The native report, reservations, console output, accounting, launch and source
binding were copied byte-for-byte from the run. The four changed code/test
files also matched the frozen source at archiving.

The [consistency audit](audit/summary.md) is **CONSISTENT**, with zero new native
checks. It verifies recorded bookkeeping, not independent proof truth.
Source binding was **UNCHANGED** before/after. Content hashes identify bytes;
they are not proofs or multiformats CIDs.

## Reproduction and isolation

Plan-only command:

```bash
env PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
python -m jevops.arena_leaf_pilot \
  --problem CallElimCorrect.extractedOldExprInVars \
  --incumbent papers/completion/lean_refactor_arena/evidence/simp-scope-strata-2026-09-25/composition-0.json \
  --profile simp-prefix-append-tree --selection-objective aggregate-local-v1
```

Snapshot: 2,119 files / 56,513,876 bytes; manifest SHA-256
`f3a85bef91e2b91aa5512fb964dc5597898d41572eeda00548fa312583abe056`;
content root `36ff03e95ebb6f48dd3fd6682c7be484460b7ba318397e7b329df0a887c8f4d3`.
Runtime directory:
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/append-tree-strata-oqidwgf7`.

Actual native command, with cwd in that snapshot's `source`:

```bash
/home/barberb/.local/bin/python -I -B -c \
  'import sys;sys.path.insert(0,sys.argv.pop(1));from jevops.arena_leaf_pilot import main;raise SystemExit(main())' \
  /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/append-tree-strata-oqidwgf7/source \
  --problem CallElimCorrect.extractedOldExprInVars --incumbent inputs/incumbent.json \
  --profile simp-prefix-append-tree --selection-objective aggregate-local-v1 \
  --execute --max-processes 34 \
  --snapshot-manifest-sha256 f3a85bef91e2b91aa5512fb964dc5597898d41572eeda00548fa312583abe056 \
  --preparation-root /home/barberb/.local/state/jevops-arena-provision-Nr5jXM \
  --projects inputs/projects.json \
  --elan-home /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/elan \
  --output /home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/tmp/append-tree-strata-oqidwgf7/experiment
```

New executions need new snapshot/output identities; never overwrite archived
evidence. The child inherited only PATH/HOME/LANG/LC_ALL, disabled external
hooks/router flags, and capped-volume TMPDIR. It used isolated Python imports,
prepared dependency bindings and the exclusive preparation lock. This is
trusted-local execution, not an OS sandbox or a claim of no other host jobs.
The 50 GB volume cap and 100 MB runtime reserve remained enforced; free space
after archiving was **276,258,816 bytes**. All caches were retained.

Recorded-result audit command:

```bash
env PYTHONDONTWRITEBYTECODE=1 JEVOPS_REGISTER_LRA_HOOKS=0 \
JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
python -m jevops.arena_report_audit \
  --protocol papers/completion/lean_refactor_arena/evidence/append-tree-strata-2026-09-25/selection-protocol.json \
  --report papers/completion/lean_refactor_arena/evidence/append-tree-strata-2026-09-25/report.json \
  --output-dir papers/completion/lean_refactor_arena/evidence/append-tree-strata-2026-09-25/audit
```

## Offline tests and files changed

```bash
env -u PYTEST_ADDOPTS PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
JEVOPS_ARENA_NATIVE_TESTS=0 JEVOPS_ARENA_DOCKER_TESTS=0 \
python -m pytest --test-seal=refresh \
  -o cache_dir=/tmp/jevops-append-tree-tests/cache \
  --junitxml=/tmp/jevops-append-tree-tests/regression-fixed.xml \
  tests/test_arena_append_tree.py tests/test_arena_simp_scope.py \
  tests/test_arena_compositions.py tests/test_arena_leaf_pilot.py \
  tests/test_arena_pareto.py tests/test_arena_aggregate.py tests/test_solver_spans.py -q
```

**659 passed, 3 skipped in 47.60 seconds** before freezing; zero reused seals,
613 fresh passes sealed. This is targeted regression, not the whole repository.
The initial run had 656 passes, three failures and three skips: new separate-line
leaf fixtures caught the renderer adding semicolons and exceeding its zero-growth
limit. The implementation was corrected to preserve discharge style, and the
same full suite rerun before any native work. Both JUnit reports are retained.

- `jevops/arena_compositions.py`: bounded source-bound support deletion and
  left-tree strategy reusing the existing exact subtree recognizer.
- `jevops/arena_leaf_pilot.py`: fixed two-path profile; existing admission,
  scoring, confirmation and resource guards unchanged.
- `tests/test_arena_append_tree.py`, `tests/test_arena_compositions.py`:
  bounds, abstention, identifier/layout preservation, growth ceiling, exact
  baseline/budget, and pre-work mutation rejection.
- `ARENA_APPEND_TREE.md`, root README, solver specialization and safety plan:
  implemented method, measured results and remaining limits.

Next: a separately frozen trial could minimize the remaining goal-only support
from this repaired source. Those edits were not tried here. Broader task
coverage, held-out evaluation, organizer-worker metric parity and production
security gates remain open. No global minimality or cross-project gain is claimed.
