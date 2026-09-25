# Protected synthetic relation canaries

`jevops.knowledge_canaries` freezes six propositional cases outside the three
development controls: conjunction/disjunction associativity, both distributive
directions, a nested disjunction swap and a three-edge permutation. These are
public, manually specified, post-development smoke tests—not secret holdouts,
randomly sampled mathematical problems, the all-15 Arena, or evidence of learned
autoencoder generalization. The seed renames binders and targets; it does not
generate new mathematical families.

The fixtures also **supply the mapped declaration names and instantiations**;
the native runner queries those names directly. Thus these are supplied-mapping
smoke tests, not independent retrieval tests. In particular, `and-or-distrib`
supplies `and_or_left`, an already available complete answer. Alpha-group
disjointness from the development examples does not exclude an equivalent
library theorem. See the [separate evaluation tracks](KNOWLEDGE_GRAPH_PROOF_PLAN.md#separate-library-reuse-from-proof-discovery)
before interpreting a token reduction as discovery or learning.

## Frozen design and proof authority

The manifest binds reference sources, explicit graph recipes, development
records, structural identity groups, both installed Lean pins, search limits,
renderings, repetitions, process ceilings and implementation identity. All six
cases are frozen before evaluating any of them. The primary comparison is
`inferred-term` against `local-term`, never whichever arm looks best afterward.
The original fully typed mapped witness remains mandatory for a graph-success
claim. Unchanged theorem statements, environment checks and axiom gates remain
those of the existing native verifier.

Each case reserves two inventory exports and 48 fresh proof measurements:
six arms × two pins × two branch orders × two repetitions. The suite's explicit
ceiling is 300 processes. Native dependency fingerprinting can reuse file
hashes, but proof receipts and sealed pytest results are not reused. Inventory
exports and graph/ingestion costs are separate from elaboration heartbeats.
Short source tokens do not imply smaller proof terms or lower end-to-end cost.

All six cases remain in the denominator, including preparation errors, rejected
proofs, budget exhaustion, abstentions and cases not reached after a storage
stop. An abstention may measure unchanged-source fallback cost but is not a
generated proof or optimization win. Summary `COMPLETE` means every case's
measurement completed; it does **not** mean every policy proposed a proof or
improved it. A strict joint improvement requires fewer tokens and lower measured
heartbeats in both orders on both pins, with all required controls/witnesses
passing. This is the existing conservative range check, not a significance test.

## Exposure and training boundaries

The single-writer **DuckDB** ledger claims all six structural identity groups
transactionally before any inventory/compiler calls. It retains exposure after
failure, interruption or reopening. Changing the seed, theorem names or proof
body cannot make a previously exposed group fresh. Later reuse must be called
regression testing; there is no retry/reset switch in this harness.

Identity ignores proposition-atom and local-hypothesis names, context order and
duplicate hypotheses, and normalizes leading implication binders into context.
It is bounded to four proposition atoms and rejects unsupported syntax. It is
structural alpha/context normalization, **not** semantic-equivalence detection
or an audit of every historical training corpus.

`assert_training_disjoint(manifest, rows)` is an explicit future admission API:
rows must have `id`, `source`, and `split="train"`; protected identities and
unsupported syntax are rejected. This harness exports no training pairs and
enables no training or promotion. The guard is not automatically installed in
every existing trainer. Retain and consistently reuse the same ledger; changing
its path does not provide global exposure protection. Filesystem ownership,
the backend and ledger location remain trusted.

## API and opt-in native runner

```python
from jevops.knowledge_canaries import CanaryLedger, make_manifest, run_canaries

manifest = make_manifest(development_records)
ledger = CanaryLedger(retained_ledger_path)
try:
    summary = run_canaries(
        manifest, evaluate_case=prepared_backend, ledger=ledger,
        output_dir=new_receipt_directory, resource_check=check_storage,
        max_processes=300,
    )
finally:
    ledger.close()
```

The injected backend owns prepared dependencies, enforces each case's two-export
and 48-proof ceilings, and returns a `run_relation_trial` report plus
`setup_processes`. The harness validates reported identity/bounds; it is not a
sandbox for a malicious callback. It performs no retries or outcome-dependent
tuning. Manifest changes during a run stop it. `processes_reserved` includes
failed-case reservations; it is not an assertion that all reserved processes ran.

The opt-in native test uses the installed Lean 4.26.0/4.29.1 pins, an empty helper
prefix, a synthetic SkillCenter-format corpus and real exported library
signatures retrieved through DuckDB. It never downloads/builds dependencies,
trains a model or restarts the watcher. Run only
`tests/test_knowledge_canaries.py::test_native_protected_relation_canaries`, with:

- `JEVOPS_RELATION_CANARY_NATIVE_TESTS=1`;
- `JEVOPS_ARENA_PREPARATION` pointing to the existing capped preparation config;
- `JEVOPS_RELATION_CANARY_RECEIPTS` naming a new, nonexistent receipt directory;
- `TMPDIR` and a **new** pytest `--basetemp` inside that existing capped volume;
- `--test-seal=off`, and `PYTHONPATH` selecting the reviewed `ipfs_datasets_py` checkout.

The ledger is retained at `cache/protected-relation-canaries-v1.duckdb` inside
the prepared volume. Existing caches, new fixtures, exports and receipts are
retained. Insufficient headroom stops evaluation; the 50 GB allowance is not
expanded and no caches are evicted. Preserve an incomplete receipt set and the
ledger instead of rerunning it as a fresh holdout.

The runner programmatically writes `manifest.json`, each inventory/plan/result,
`summary.json` and `summary.md`. The native pytest assertion checks accounting
and receipt production, **not that the optimizer wins**. Inspect the generated
summary and individual reports for actual native coverage and outcomes.

## Retained observations (2026-09-24)

The [generated six-case summary](papers/completion/lean_refactor_arena/evidence/knowledge-relation-canaries-2026-09-24/summary.md)
records **4/6 eligible native paired comparisons and 3/6 strict joint
improvements**. All 288 fresh proof observations verified, with 12 additional
inventory-export processes and no receipt-cache reuse. That includes unchanged
fallback proofs; it does not mean six generated graph successes.

Conjunction associativity, conjunction-over-disjunction distribution and the
nested disjunction swap reduced compact-local token counts from 27/66/16 to
1/1/5, respectively, with lower raw heartbeats in both orders on both installed
pins. The three-edge permutation used fewer heartbeats but increased tokens
from 9 to 17, so it is a tradeoff, not a joint improvement. Disjunction
associativity and disjunction-over-conjunction distribution exhausted the fixed
256-state mapped-search budget. Their displayed candidate token counts are
unchanged-source fallback measurements, not inferred proof discoveries.

The 66→1 distribution comparison uses the generated compact-local baseline;
the original constructor reference is 57 tokens. The one-token body is
`_root_.and_or_left`: one qualified lexical identifier, with the shared library
providing its proof. No new helper is hidden in that candidate, but neither
elaborated proof size nor independent premise-discovery cost follows from the
source-token count. Preserve the original receipts; do not relabel this result
as an unbiased retrieval or autoencoder benchmark.

The [regression receipt](papers/completion/lean_refactor_arena/evidence/knowledge-relation-canaries-2026-09-24/regression.xml)
records **374 passed, 25 skipped**; the separately opted-in
[native receipt](papers/completion/lean_refactor_arena/evidence/knowledge-relation-canaries-2026-09-24/native.xml)
records one completed suite run. Full sources, inventories, frozen plans,
per-pin/order raw heartbeats and artifacts are retained alongside the summary.
The source Parquet, DuckDB artifacts, exposure ledger and test caches remain on
the existing capped volume. No model calls, training, promotion, watcher changes,
downloads, cache eviction or storage expansion occurred. These are synthetic
post-development observations, not an Arena high score or blind generalization.

## Follow-up boundary

The fixed run is diagnostic, not an invitation to tune on a protected score.
Once observed, these cases are exposed regression cases. Preserve their first
receipts and the exposure ledger when investigating failures.

One search behavior worth a separate development experiment is retaining a
valid incumbent when further exploration exhausts a budget. The current search
continues constructing alternatives even when the goal already occurs in its
facts; its global exhaustion flag makes the relation proposer abstain. A future
policy could prioritize exact facts and return a bounded best-so-far proposal,
while recording incomplete search and still requiring the original typed mapping
witness and all native checks. That would not establish shortest-proof
optimality. Do not raise budgets or enable such a policy midway through a frozen
run. Compare it as a separately frozen regression experiment, then use genuinely
new structural families for subsequent holdout claims.

Any later training path still needs independently admitted training data,
verified targets, CE/cosine controls and unchanged proof/cost gates. Neither a
successful one-token library reference nor a compiled fallback is, by itself,
evidence that an autoencoder learned compression.
