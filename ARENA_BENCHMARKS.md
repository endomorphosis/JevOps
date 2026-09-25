# Full-corpus token and heartbeat benchmarks

Keep the warm-up corpus fixed at **15 problems / 36 version pins**. Running the
available subset does not make missing historical revisions or Putnam imports
pass. Compiler installation alone is not readiness.

For a fixed saved-candidate benchmark, use a frozen runtime and inputs as in
[ARENA_FROZEN_RUNS.md](ARENA_FROZEN_RUNS.md), then:

1. Run `python -m jevops.arena_lean --baseline` with explicit `--corpus`,
   `--projects`, `--elan-home`, `--max-processes 36`, bounded `--timeout`,
   `--isolation trusted-local`, and a new `--output baseline.json`.
2. For each preselected refactor, run `python -m jevops.arena_trial --run` with
   the same frozen inputs, its explicit `--problem` and `--candidate` (or
   `--seed-candidate`), `--proposal-cap 0`, `--repetitions 2`, `--seed 17`,
   and a new output file. Reserve eight calls per required pin: two arms,
   two orders, two repetitions. Do not select winners after inspecting this
   benchmark. Unchanged problems remain baseline-only.
3. Generate the summary, without making any additional Lean calls:

   ```bash
   python -m jevops.arena_benchmark_report \
     --corpus /frozen/inputs/corpus.jsonl \
     --baseline /results/baseline.json \
     --trial /results/trial-subst.json \
     --trial /results/trial-extracted.json \
     --trial /results/trial-core.json \
     --output-dir /results/new-summary
   ```

The generator writes `report.json` and `summary.md` programmatically and refuses
overwriting an existing directory. It checks corpus identity, all 36 rows,
reference-token calibration, source/request/receipt agreement, controlled
schedules, native invocation accounting, and axiom growth. This checks recorded
claims, **not authenticity or proof validity**; only the native runs supply the
observations. Saved-report tests do not count as fresh Lean executions.

Token totals count each problem once using `lra-reference-lexical/v1`. Declared
candidate lengths are static counts; an accepted full-set total stays null
until every required check passes. Missing and rejected heartbeat observations
are never zero. Per-refactor reductions compare repeated controls and candidates
within each exact version and branch order. Raw heartbeat counts divided by
1000 give Lean display units, **not milliseconds**. Baseline ranges across pins
are not cross-version speedup comparisons.

There is no inferred full-set heartbeat reduction or official Arena score.
Organizer-worker parity remains unconfirmed. These are trusted-local runs,
not a hostile-metaprogram sandbox, canary generalization study, autoencoder
training evaluation, tactic search, or automatic production promotion.

## Completing missing environments without repeating measured rows

A continuation uses the same frozen corpus and native runtime, with a new
project manifest containing **only previously unavailable environment pins**.
Run the baseline CLI with that manifest, retaining all 36 rows. Omitted bindings
must appear as `prepared_project_binding_missing_or_ambiguous`, not as successes.
Then add `--continuation /results/additional-baseline.json` to the report command.
Multiple disjoint continuations may be supplied in order.

The reducer validates every input matrix and verified receipt before combining
them. It refuses overlapping attempts and cannot replace earlier failures or
measurements with better-looking results. New failures replace old readiness
gaps and stay visible. The report records an originating report hash per row
and labels coverage as cumulative: earlier checks were **not** rerun. This does
not establish that old environments are still available or authenticate saved
receipts. Keep original reports, frozen inputs and snapshot checks alongside
the generated summary. No full-set heartbeat aggregate is inferred.

## Dependency-check overhead

The prepared `fuse.ext4` project volume has files with whole-second change
timestamps. `seals.Fingerprinter` deliberately disables its stat-to-digest fast
path for these files and rehashes their bytes. Repeated dependency scans can
therefore dominate the benchmark's wall time even when proof heartbeats are
low. This is separate from theorem elaboration cost. Do not disable that
fallback to improve benchmark numbers; investigate a reliably timestamped
prepared filesystem under an explicit storage budget for faster future runs.

## Recorded run

The [2026-09-23 full-set report](papers/completion/lean_refactor_arena/evidence/native-full15-benchmark-2026-09-23/summary.md)
was generated from fresh baseline and controlled-trial receipts, archived beside
the summary with the fixed measurement plan and snapshot identities. Its
`INCOMPLETE` status preserves missing environment checks; it is not an official
Arena result or evidence of autoencoder training.

The [first continuation](papers/completion/lean_refactor_arena/evidence/native-full15-continuation-2026-09-23/report/summary.md)
adds three native baseline checks from pinned CSLib/ArkLib v4.30 environments:
23/36 checks, with nine problems fully covered. It retains earlier observations
and labels them as historical, not freshly rerun. One ArkLib reference differs
from the pinned source by an internal space; the exact-source locator still
rejects that binding. A formatting diagnosis is not proof evidence.

The [Putnam continuation](papers/completion/lean_refactor_arena/evidence/native-full15-putnam-continuation-2026-09-23/report/summary.md)
adds all three Putnam v4.25 baselines: 26/36 checks, every problem covered on at
least one pin, and nine problems fully covered. The remaining ten checks stay
unavailable. Source-token totals remain 17595 → 17474, with no accepted full-set
total or aggregate heartbeat score. The generated archive includes preparation
failures/retries, the source-location diagnostic, and storage preflight results.

For shallow dependency clones, Lake release fetching may fail even at the
correct commit because the local release tag is absent. Restore only upstream
tags whose peeled commit equals the locked revision; do not substitute a newer
release, edit the lockfile, or count a successful cache download as verification.
Archive failed preparation logs as well as successful retries. The 50 GB
preparation cap and free-space preflight remain separate from proof admission;
retaining all environments can prevent further version coverage.
