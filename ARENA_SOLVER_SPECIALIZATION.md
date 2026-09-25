# Checked solver specialization and bounded discovery

## Joint support follow-up: an aggregate trade-off

The [`simp-prefix-drop-second` profile](ARENA_APPEND_TREE.md) nominates one
predeclared positional support deletion using the existing bounded engine.
From the confirmed 168-token Strata source it completes the pair of individually
valid `getVars` deletions. Offline tests establish byte identity in both correctly
indexed deletion orders, not proof or cost validity.

The [fresh trial](papers/completion/lean_refactor_arena/evidence/prefix-joint-strata-2026-09-25/README.md)
verified all 30 checks: **166 tokens**, but **1.56265% more raw heartbeats** than
168 tokens. The **+0.14247 local combined-score gain** passes the predeclared
aggregate gate; strict-dual rejects it. Retain both Pareto candidates, including
168 as the faster alternative. Target/axioms were unchanged; 725 offline tests
passed / three skipped; snapshot and audit passed. No training or promotion.

## Complete bounded single-deletion neighborhood (opt-in)

The `simp-prefix-single-deletions` composition/leaf-pilot profile reuses the
goal-only prefix recognizer and source-bound edit mechanism. It tests each
single deletion from one to four distinct support entries, always from the
same seed. Larger/duplicate lists abstain rather than silently truncating the
trial. Whole-source proof checks and fresh cost confirmation remain mandatory.

The [first completed trial](papers/completion/lean_refactor_arena/evidence/prefix-deletions-strata-2026-09-25/README.md)
confirmed 170 → 168 tokens, 11.87453% fewer raw heartbeats and +1.66129 local
combined-score points. Two deletions verified, two failed; the better valid
draft alone was confirmed. All 18 confirmation checks preserved the target
and original axiom set. Total: 42 native checks; 716 offline passes / three
skips, unchanged snapshot and consistent audit. Combining the two valid edits
is untested. No global minimality, held-out gain or production promotion claim.

## Joint support deletion and continuation repair (opt-in)

The [`simp-prefix-append-tree` profile](ARENA_APPEND_TREE.md) extends the existing
composition/leaf pilot with a fixed deletion-only control and a joint edit:
remove append normalization from a goal-only induction prefix, then reconstruct
one exact three-leaf append proof in left-associated form. It reuses source-bound
edits and the bounded subtree matcher. Neither nomination independently proves
applicability; both require fresh whole-proof checking and cost measurement.

The [first native trial](papers/completion/lean_refactor_arena/evidence/append-tree-strata-2026-09-25/README.md)
confirmed 172 → 170 tokens, 3.61223% fewer raw heartbeats and +0.72983 local
combined-score points. Deletion alone failed all four screening checks; the
joint repair passed all six independent confirmation checks with unchanged
axioms. Total: 34 native processes, 659 offline tests passed / three skipped.
The fixed profile, source hashes, rejected control and complete receipts are
archived. No paid model, build, official score or production promotion occurred.

## Narrowing shared simplification scope (opt-in)

`python -m jevops.arena_leaf_pilot --profile simp-prefix-scope
--selection-objective aggregate-local-v1 --problem NAME --incumbent DRAFT.json`
plans two fixed source nominations without running Lean. The existing
composition/selection pipeline is reused; the strict-dual default is unchanged.

For the deliberately restricted multiline prefix
`intro h; induction x <;> simp only [names] at *`, the variants replace only
the location suffix with (1) no suffix, simplifying the goal, or (2) `at h ⊢`,
simplifying the explicit introduced hypothesis and goal. The support list,
theorem envelope and every following proof byte stay unchanged. The name is
copied from the single explicit intro, never guessed from generated Lean names.

This is a bounded layout nomination, **not a Lean parser, scope proof, or
equivalence rule**. It abstains on comments, tabs/CRLF, nested/multiline support,
multiple introduced names, composed trailing tactics, unsupported prefixes,
over 32 support entries, or oversized bodies. The exact source-bound edit is
revalidated, and every draft must pass independent whole-source Lean checking.
Removing hypothesis simplification can break the continuation even if the
visible goal appears unchanged. No historical profiler span or receipt is
used as current admission authority.

With the confirmed 174-token source, the two drafts have 172 and 175 tokens.
The frozen one-pin ceiling is **34** processes: sixteen screening checks
(original, incumbent, two drafts; two repeats in both orders), then eighteen
fresh checks for only the fixed winner (three repeats/order). No retries or
post-result expansion. The 174-token aggregate baseline must not be replaced
by the older 169-token shorter baseline to make an aggregate win easier.
Keep the 169-token source separately for future strict-dual work. The new
proposal helper's `solver_feedback.py` and `rewrite_policy.py` dependencies
are included in composition-plan source hashes, in addition to existing ones.

The [first frozen scope trial](papers/completion/lean_refactor_arena/evidence/simp-scope-strata-2026-09-25/README.md)
confirmed the **172-token goal-only** variant: **7.70% fewer raw heartbeats**
and **+1.29287 local combined-score points** versus its 174-token incumbent.
All 34 checks verified without axiom growth. The 175-token alternative also
qualified in screening but was not independently confirmed. Future aggregate
trials should use the 172-token source; the distinct 169-token shorter baseline
remains for strict work. No general/corpus-wide speedup or promotion is claimed.

## First-site, original-normalized trial (opt-in)

`python -m jevops.arena_solver_pilot --comparison prefix-reference-v1
--problem NAME --incumbent DRAFT.json` emits a plan without executing Lean.
This is one search arm, not a matched controller comparison. It uses the
existing `balanced-frontier-v1` search with 16 calls, four retained states,
depth two, one solver site per checked source, and one final nominee. Native
parser inventories bind complete tactic replacements; profiler display hints
and old offsets are not edit anchors. Other solver sites are explicitly omitted.

`discovery-reference-v1` nominates against the original reference denominators,
allowing token growth when heartbeat savings compensate. Fresh
`aggregate-local-v1` selection compares the nominee with both the original and
the supplied incumbent: two screening repetitions/order followed by three
fixed-winner confirmation repetitions/order. For one pin and a non-original
incumbent, the ceiling is **48** native checks (2 controls, 16 discovery,
12 screening, 18 confirmation); unused capacity is not reallocated. With the
original as seed it is 37. This is not strict-dual selection or automatic
promotion. All legacy profiles retain their original limits and objectives.

The bounded prefix hypothesis follows the Strata profiler's shared-simplifier
hotspot. That trial's comparator was the recovered **169-token** source,
not the historical 185-token baseline below. New trials must use the current
objective-appropriate incumbent, not simply rerun an easier old baseline. Historical support lists are
proposal information, not current proof or cost evidence.

The [first frozen prefix trial](papers/completion/lean_refactor_arena/evidence/prefix-reference-strata-2026-09-25/README.md)
confirmed a 174-token candidate: +5 tokens but 21.49% fewer raw heartbeats and
+2.77627 local combined-score points versus the 169-token incumbent. All 30
screening/confirmation checks verified without axiom growth; the full trial
used 42/48 reserved calls, including six rejected support deletions. The
shorter incumbent is retained; there is no strict-dual win or promotion.

## Location-preserving support deletion

`support_edits()` now recognizes single-line explicit support lists ending in
`at *`, a named hypothesis, a space-separated list of hypotheses, or `⊢`.
It preserves the location, LF/CRLF ending, exact source binding, and untouched
continuation. Previously, `at *` lists were silently skipped even when they
came from an accepted compiler suggestion. Empty support and one-entry
deletions remain **unverified proposals** until whole-source replay succeeds.
The 32-entry/site/source bounds and restrictions on comments, tabs, nested
terms, and metaprograms are unchanged. Multiline support-list deletion is not
implemented; parser-bound suggestion replacement is a separate operation.

The [bounded Strata experiment](papers/completion/lean_refactor_arena/evidence/solver-support-strata-2026-09-25/README.md)
starts from the 190-token aggregate candidate but keeps the distinct 185-token
incumbent for strict-dual selection. A 188-token deletion is not a strict win
over that incumbent. Search uses the existing `minimize-v1` mode and native
checker; no new agent framework, model call, or automatic promotion is added.

## Aggregate-objective nomination (opt-in update)

`discover_solver_frontier(..., draft_policy="discovery-aggregate-v1")`, also
available through `ArenaLocalRuntime.discover_solver`, permits longer final
drafts. It ranks already checked nodes by the exact sum of seed-normalized
token and heartbeat reductions, keeps only positive gains, and abstains if
either seed denominator is zero. Existing call/state/depth/source-byte caps,
full-source replay and exact-source deduplication remain unchanged. A failed
composition never becomes eligible merely because its component edits passed.

This single-pin, single-sample nomination is a heuristic, not an Arena score or
an admission decision. With a non-original seed, its seed-normalized weights
can differ from final reference-normalized selection; nomination is not a
guarantee of retaining the best aggregate candidate under a finite draft cap.
Feed nominated four-field drafts to the fresh selector
with `selection_objective="aggregate-local-v1"` for all-pin checking and
fixed-winner confirmation. The default `shortest-v1`, existing
`discovery-dual-first-v1`, and the older strict-dual pilot's frozen protocol
are unchanged. See [aggregate selection](ARENA_PARETO_SELECTION.md#aggregate-local-score-opt-in).

## Original-reference nomination

`draft_policy="discovery-reference-v1"` fixes the weighting mismatch for a
non-original seed without changing the older policies or pilot profiles.
For each checked candidate, it computes the exact rational nomination gain

```
(seed_tokens - candidate_tokens) / original_tokens
+ (seed_raw_heartbeats - candidate_raw_heartbeats) / original_raw_heartbeats
```

The token denominator is recomputed from the original source. The heartbeat
denominator is the original branch of the seed's fresh verification request,
not a published/display-unit cost or a later candidate-specific observation.
The report records that request identity, source hash, denominators and exact
gains. This reuses an existing observation: no extra verifier call is made.
Missing/zero denominators yield no nominee; malformed observations are rejected.
Only the first declared (primary scoring) pin is supported by this policy.

This is a single-sample discovery estimate, not confirmation or calibrated
uncertainty. A positive improvement over the seed need not beat the original.
Use `aggregate-local-v1` for fresh all-pin checking and confirmation against
both original and incumbent. Source search, budgets, full-proof checking and
the default shortest filter are unchanged. The historical
`aggregate-nomination-v1` pilot still compares its original two policies.

## Frozen aggregate nomination comparison

`python -m jevops.arena_solver_pilot --comparison aggregate-nomination-v1
--problem NAME` emits a plan without launching Lean. This new opt-in profile
runs `balanced-frontier-v1` twice, with separate guards and identical eight-call,
four-state, depth-two, two-site and one-draft caps. Only the final nomination
policy changes: `discovery-dual-first-v1` versus `discovery-aggregate-v1`.
Their per-arm labels/policies, common limits and common final objective are
bound into the frozen plan. The old pilot profiles remain strict-dual.

Every declared pin receives fresh original and optional incumbent controls.
The exact-source union of the two nominees enters `aggregate-local-v1`
screening (two repeats/order), followed by fresh fixed-winner confirmation
(three repeats/order). Only the union winner is confirmed; a losing nominee
has screening observations, not an independently confirmed performance claim.
No candidate or an infrastructure failure in one arm is hidden from the report.
No post-result search expansion, alternative confirmation or promotion occurs.

For one pin, the full ceiling is 41 checks with the original as seed, or 52
with an explicit non-original incumbent. Exact duplicate nominees reduce actual
selection work; unused capacity is not reallocated to more discovery. The CLI
still requires `--execute`, the exact `--max-processes`, frozen source identity,
prepared projects, capped storage and the exclusive preparation lock.

This compares nomination, not a different search algorithm: both arms may
produce identical checked frontiers. Report neutral cases as such, and keep
discovery measurements separate from fresh selection. Seed-normalized
nomination also retains the non-original-seed limitation documented above.

The [first matched Strata run](papers/completion/lean_refactor_arena/evidence/solver-nomination-strata-2026-09-24/README.md)
finished `NO_CANDIDATE`: 18 native checks, the same two source nodes in both
arms, and no screening/confirmation. The valid 197-token alternative to the
185-token incumbent cost about 2.13% fewer heartbeats but 6.49% more tokens.
Neither nomination policy emitted it. The full diagnostics identify two
first-line-only replacements of a multiline `simp` that Lean rejected; complete
source-span handling was the next intervention at that time; it is now
implemented separately below, without rewriting those historical results.

## Original solver-specialization slice

This implements the first solver-specialization slice of the
[research plan](LEAN_REFACTOR_ARENA_RESEARCH_PLAN_2026_09_24.md), using the existing
Arena checker, local runtime and fresh selector. It is deterministic proposal
generation, not a trained policy, an autonomous service or a new proof authority.

## Run the offline control

```bash
python -m jevops.arena_solver --demo
```

This emits JSON with three isolated arms, the same synthetic verifier, seed and
12-call ceiling. No Lean, network, model, credentials, downloads or files are
needed. Costs are manufactured fixture values, **not measured Lean heartbeats**.

| Arm | Discovery actions | Retained token counts | Calls | Smaller drafts |
| --- | --- | --- | ---: | ---: |
| `suggestions-v1` | Only immediately shorter solver suggestions | 7 | 2 | 0 |
| `minimize-v1` | Also replay explicit-support deletions | 7 | 2 | 0 |
| `frontier-v1` | Also keep checked equal/longer intermediate sources | 7 → 8 → 5 | 8 | 1 |

The intermediate has synthetic cost 7,000 versus the seed's 10,000; the final
draft has 4,000. This deliberately constructed control demonstrates a search
barrier, not an Arena improvement or evidence about the prevalence of such
barriers. The two shortening-only modes finish with unused allowance. They are
matched controls in the **new** engine, not reproductions of every legacy
harvester behavior. Wall times in the JSON are measured orchestration time.

## Integration and trust boundary

- `solver_feedback.py` provides exact-source-bound `SolverEdit` nominations.
  The legacy `suggestions()` and `harvest_solver_feedback()` contracts remain
  unchanged. The native span-aware path aggregates compatible anchored
  suggestions under the bounds below. `support_edits()` tries an
  empty explicit support list followed by one-entry deletions.
- `ArenaEvaluator.verify_request()` checks one explicit pin using the same
  context, typed-receipt, target, process and axiom boundary as `evaluate()`.
  A foreign context/pin fails before verifier work. No legacy `theorem_ok`
  dictionary can stand in for a receipt.
- `ArenaCheck.lean` now includes the diagnostic filename and position. Only
  information messages at the exact queried tactic in `ArenaCandidate.lean`
  can nominate an edit. A successful `simp?`/other query does **not** authorize
  its printed replacement: that replacement receives its own whole-source check.
- `arena_solver.py` expands a deterministic FIFO queue of complete, checked
  sources. An edit preserves the statement, prefix and subsequent proof text.
  Complete-source checking catches failures in that continuation. A support
  list is not the complete logical dependency set: tactics may still use local
  context and built-in reductions. Neither minimum support nor global proof
  minimality is established.
- `ArenaLocalRuntime.discover_solver()` reuses an explicitly supplied native
  guard. Unlike local capture/search, it consumes **the guard's whole-proof
  process budget**, not the runtime's local-stage budget. Stage fixtures cannot
  be substituted for this guard. Endpoint/execution restrictions are unchanged.

## Parser-bound solver edits

The native checker exports `solver_spans` with schema
`jevops-lean-solver-spans/v1`. It reparses the exact candidate in the original
prefix environment **after both measured branches**; this traversal is outside
the reported heartbeat intervals. It is extra orchestration work, not free
total runtime. Traversal is bounded to 100,000 nodes, depth 256 and 256 spans.
Exhaustion yields `UNSUPPORTED` with no partial inventory. The driver content
hash changes its verifier identity; old receipts are not fresh evidence for
the changed implementation.

Spans use original-source UTF-8 byte offsets, including CRLF bytes. The Python
adapter validates the schema, source byte length, bounds and character
boundaries, then creates exact-source-bound edits at complete tactic spans.
Each newly verified frontier node receives its own inventory; edits never
reuse positions from a parent source. The surrounding `<;>` and the following
proof remain outside the edit. Source/diagnostic authority still comes from the
existing typed receipt and whole-source verifier, not the parser observation.

At a repeated tactic location (for example, `induction ... <;> simp? ...`),
messages can describe different goals. `diagnostic_edits` considers **all**
anchored suggestions, not the first four alternatives. When every message is
a compatible explicit `only` list, it emits their stable-order union, preserving
the source's location (`at *`, a named hypothesis, or the goal). Pretty-printed
multiline lists are accepted by a deliberately narrow name-list grammar.
Mixed tactics/locations, unsupported terms, clipped messages, more than 64
union entries, and ambiguous multi-command scripts abstain. Even a compatible
union can change simplifier behavior: it is only a nomination and must pass
fresh whole-source checking before joining the frontier.

This is conservative multi-message aggregation, **not** serialization of full
goal states or reconstruction of branch-specific proof scripts. Inline tactics,
trailing combinators and the existing unsupported comments/metaprograms remain
outside this slice. The legacy harvester keeps its single-line output contract;
without parser metadata, query discovery now skips unclosed delimiters and
ambiguous continuations instead of editing a multiline command's opening line.
This intentional safety restriction can reduce legacy proposal coverage.

The span repair alone changes no scoring weights, nomination policies, search
order, promotion behavior or process budgets. The archived Strata trial remains `NO_CANDIDATE`; its
old malformed edits remain in the archive for regression testing.

Offline regression:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_ARENA_NATIVE_TESTS=0 \
  python -B -m pytest -q --test-seal=off -p no:cacheprovider \
  tests/test_solver_spans.py tests/test_solver_feedback.py \
  tests/test_arena_solver.py tests/test_arena_solver_balanced.py \
  tests/test_arena_solver_pilot.py -k 'not real_'
```

Explicit installed-toolchain controls are
`tests/test_arena_solver_native.py::test_native_multiline_solver_spans_and_per_goal_hints`.
They need `JEVOPS_ARENA_NATIVE_TESTS=1`, an explicit `ELAN_HOME` and
`JEVOPS_SEARCH_LEAN_TAG`, and must be run serially under the preparation lock
with scratch files on the validated capped volume. They never download models,
toolchains or dependencies. Each newline variant reserves three whole-proof
checks; fixture tests alone do not establish native parser behavior.

The [native repair controls](papers/completion/lean_refactor_arena/evidence/solver-span-repair-2026-09-24/README.md)
passed both newline variants on Lean 4.26.0 and 4.32.0 (12 whole-proof checks),
then freshly verified the exact Strata multiline replacement in three checks.
That replacement is 190 tokens versus the 185-token incumbent, with lower
single-observation heartbeats. In that initial control it was an unconfirmed
longer/faster intermediate, not a nominated score winner. Its targeted offline
regression passed 632 tests.

The separate [fixed-candidate confirmation](papers/completion/lean_refactor_arena/evidence/solver-reference-strata-2026-09-24/README.md)
subsequently passed all 30 fresh checks under `aggregate-local-v1`: about
11.84% fewer heartbeats and +2.76779 local score points versus the incumbent.
It also beats the original in both costs. This confirms that fixed source's
local trade-off, not the superiority of `discovery-reference-v1` over another
discovery policy. There is no automatic promotion or official Arena score.

### Using the native discovery adapter

For an already prepared record and guard:

```python
from jevops.arena_local import ArenaLocalRuntime
from jevops.arena_solver import SolverLimits
from jevops.arena_trial import Candidate
from jevops.arena_pareto import selection_plan, run_selection

runtime = ArenaLocalRuntime(guard, record)
discovery = runtime.discover_solver(
    pin, mode="frontier-v1", limits=SolverLimits(max_calls=16))

# Four-field JSON drafts can also feed the existing arena_pareto CLI.
# Do not pass discovery receipts/costs as admission or confirmation evidence.
drafts = [Candidate(d["label"], d["source"], d["provenance"])
          for d in discovery["drafts"]]
if drafts:
    plan = selection_plan(record, drafts, selection_objective="strict-dual-v1")
    result = run_selection(
        record, drafts, fresh_verifier_factory,
        max_calls=plan["required_request_budget"], evidence_mode="local_lean",
        selection_objective="strict-dual-v1")
```

The caller must provision `guard`, `pin`, `record` and the fresh factory using
the [existing native bindings](ARENA_NATIVE_VERIFIER.md) and
[selection protocol](ARENA_PARETO_SELECTION.md); this snippet does not infer
project revisions or reserve resources for the caller. When the discovery seed
is a non-original incumbent, pass that incumbent explicitly to **both** selector
calls too. Defaulting to the original would compare against the wrong incumbent.

With the default shortest nomination, every reported discovery draft is shorter
than both seed and frozen reference, but may be slower or incompatible with
other pins. Aggregate nomination also allows longer drafts. The strict selector must
check every declared pin, both branch orders and repeated fresh measurements,
then confirm the selected candidate in new processes. The discovery incumbent
is never overwritten. Single discovery observations merely order/report states;
they do not justify a cost-improvement claim. The reported Pareto subset does
not prune the search queue.

## Bounds, context and outcomes

Defaults are 16 calls, 12 retained states, depth 3, four sites per source/action
family, 128 edit nominations, 64 KiB per source, 256 KiB retained source bytes
and four returned drafts. All are validated integers; zero work is not replaced
by a nonzero default. Hard caps are 64 calls, 16 states, depth 4, eight sites,
256 nominations, 64 KiB/source, 1 MiB retained sources and eight drafts.

Calls are reserved before invoking the verifier; native process limits and
per-process time/heartbeat limits remain additional independent constraints.
The report distinguishes verifier invocations from actual native processes
(available on the guard). Failed checks are charged. There are no automatic
retries, disk caches or refunds. Exact-source deduplication suppresses repeated
work in this run; it is not a fresh verification event. This is single-owner,
single-process orchestration, not concurrent worker locking.

State admission is first-fit FIFO under count/byte caps. Sites use source order,
which can disadvantage later tactics under a bound; no search completeness is
claimed. `omitted` reports query-site omissions, support windows that had at
least one omitted site, state/byte caps, duplicate/unsupported/non-shorter edits
and draft truncation. Hitting the edit-depth cap also marks `truncated`.
Receipts are bounded by the existing 128 KiB observation limit and 64 calls
(roughly 8 MiB of observations before JSON escaping/metadata). The existing
receipt schema separately permits up to 1 MiB of axiom-output text per receipt;
normal native output is much smaller, but that additional worst-case storage
must not be confused with the retained-source byte cap. Edit/probe counts and
source sizes are separately bounded. There is no crash-resume or whole-run
deadline promise.

The plan binds the immutable Arena context, seed, pin, limits, mode and relevant
implementation content hashes. Live dependency validation precedes each check
and runs again at return. Implementation changes abort discovery. Hashes are
identities, not proofs or signatures. A changed final context suppresses drafts;
historical attempts remain in the report with `context_applicable: false`.
These checks trust the injected verifier and host; this is not a sandbox for
arbitrary Lean metaprograms or an authentication protocol for uploaded receipts.

`COMPLETE` means the bounded protocol finished, not that a target won or an
optimum was found. Other statuses are `SEED_REJECTED`, `BUDGET_EXHAUSTED`,
`TIMEOUT`, `UNAVAILABLE` and `ERROR`. Candidate semantic rejection discards that
branch; infrastructure failure stops the run without relabelling it a failed
theorem. Previously checked drafts may survive budget/timeout/unavailability
if the final context remains applicable; `ERROR` suppresses all drafts. Every
report has `promoted: false`, `proof_admitted: false`, `training_enabled: false`,
`official_score: null` and no measured API cost.

## Coverage and limitations

Offline tests cover the longer-intermediate barrier, exact source/diagnostic
binding, malformed receipts, forged flags, required support and continuation,
duplicate work, zero/exact budgets, all storage limits, stale context and the
fresh all-pin selector boundary (including failed confirmation).

`tests/test_arena_solver_native.py` is an explicit opt-in installed-Lean control.
It compares all three arms on a redundant stdlib `simp only` list, checks real
diagnostic anchors and separately replays suggestions/deletions. Run it serially
under the prepared workspace lock and disk cap; it never downloads/builds
dependencies or substitutes versions:

```bash
# Set these to an already prepared toolchain and a fresh capped-volume directory.
JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_SEARCH_LEAN_TAG=v4.26.0 \
  ELAN_HOME=/prepared/elan TMPDIR=/prepared/tmp \
  python -m pytest -q -s --test-seal=off -p no:cacheprovider \
  --basetemp=/prepared/new-solver-test tests/test_arena_solver_native.py
```

This first slice deliberately excludes nested/branching solver scripts, Aesop
extraction, AST-aware rewrite merging, global support minimization, learned
allocation, equality saturation and production promotion. Multiline support is
a conservative straight-line syntax subset, **not** a complete Lean parser.
Queries are attempted only where the installed pin/environment supports them;
unsupported tactics fail normally, not via implicit imports or provisioning.
The stdlib controls are not held-out Arena tasks. No new Arena score, trained
model quality or corpus-wide heartbeat improvement follows from them.

## Observed validation, 2026-09-24

The [condensed results](papers/completion/lean_refactor_arena/evidence/solver-specialization-control-2026-09-24.json)
record the tested implementation hashes, per-arm counters and observations.
They summarize stdout; they are not an importable native receipt archive.

| Installed Lean | Best tokens, every arm | Raw heartbeats, seed → best | Suggestion / minimizer / frontier calls |
| --- | --- | --- | --- |
| 4.26.0 | 10 → 6 | 29,953 → 24,727 | 4 / 12 / 12 |
| 4.29.0 | 10 → 6 | 26,710 → 21,408 | 4 / 12 / 12 |

Both native tests passed (243.63 s and 274.62 s respectively; 56 total native
processes). All three arms reached the same best result: broader discovery cost
three times as many checks, without an additional benefit on this simple
control. The apparent 17.45%/19.85% raw-heartbeat reductions are **single-state
observations per arm**, not fresh cost-confirmed Arena gains. Only reference-first
order was measured. No native strict-dual selection was run on these drafts.
Reported search wall time includes live dependency validation but excludes guard
construction; total pytest times also include setup and test overhead.

Exact targeted offline regression command (440 passed, 5 skipped, 89 deselected):

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 \
  JEVOPS_USE_EXTERNAL_ROUTER=0 JEVOPS_ARENA_NATIVE_TESTS=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_arena.py tests/test_arena_lean.py tests/test_arena_trial.py \
  tests/test_arena_pareto.py tests/test_arena_local.py tests/test_arena_solver.py \
  tests/test_arena_solver_selection.py tests/test_arena_solver_native.py \
  tests/test_solver_feedback.py tests/test_typed_terms.py tests/test_proof_metrics.py \
  tests/test_router_tuning.py \
  -k 'not real_ and not compiled_expression and not mathlib_expression and not compiler_generates'
```

The native command above ran once with each tag, under
`arena_prepare.exclusive(root / "single-build.lock")`, after
`validate_volume(preparation.json)`. Here `root` was
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM`, `ELAN_HOME=root/work/elan`,
`TMPDIR=root/work/tmp`, and the fresh `--basetemp` paths were
`root/work/solver-frontier-20260924-C8aSDT/v4.26.0` and
`root/work/solver-frontier-20260924-C8aSDT/v4.29.0`. The same three external-hook/
dependency/router flags were zero. No download or dependency build occurred;
the validated capped volume retained about 2.63 GB free. No whole-repository
test-suite pass is claimed. `git diff --check` and Python compilation checks
also passed for this slice.

## Frozen public-Arena pilot

`jevops.arena_solver_pilot` connects discovery to the existing fresh selector.
Its default invocation only emits a plan; no model, Lean process, provisioning
or lock acquisition occurs:

```bash
python -m jevops.arena_solver_pilot --problem \
  Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema
```

The fixed protocol compares all three solver modes with eight calls, four
retained states, depth two, two sites and one nominated draft per mode. The
reference and an optional non-original incumbent first receive independent
controls on every declared pin. The exact-source union of the per-arm drafts
then enters `strict-dual-v1`, with two screening and three fresh confirmation
repetitions in both branch orders and a predeclared 100-raw-heartbeat floor.
That floor is a fixed conservative policy, not a statistically calibrated
noise estimate. Discovery receipts do not count as selection measurements.

For the one-pin Physlib task and original seed, the full reservation is **53**:
one control + three × eight discovery calls + up to 16 screening and 12
confirmation calls. Fewer distinct drafts reduce actual selection work; unused
search allowance is not transferred to another arm. A failed control stops
discovery. An infrastructure/seed failure in any arm makes the comparison
incomplete and prevents selection; it is not removed from the denominator.
Reaching a declared search budget is a bounded-search outcome, not such a
failure. Valid drafts from a budget-truncated arm still need fresh selection.

Use an [immutable source snapshot](ARENA_FROZEN_RUNS.md), put prepared project
mappings under its `inputs/`, and launch the **copied** module with isolated
Python imports. Native execution additionally requires `--execute`, the exact
`--max-processes` ceiling from its plan, `--snapshot-manifest-sha256`,
`--preparation-root`, `--projects`, `--elan-home`, and a new `--output` directory.
The runner acquires the existing nonblocking `single-build.lock`, validates the
50 GB volume and capped `TMPDIR`, and retains a 100 MB free-space reserve. A busy
lock means no run started; it never launches parallel native work or kills the
owner. Missing pins require separate preparation, never automatic substitution.

For a non-original incumbent, provide a matching four-field `--incumbent` draft
from the snapshot. Its historical receipt is not imported; controls and both
selection phases recheck it. The incumbent comparison label is normalized to
avoid collisions with newly generated draft labels.

Outputs include the frozen plan, fsynced reservations, all-pin control receipts,
complete per-arm discovery reports, untrusted four-field draft files, the fresh
selection plan/report when applicable, accounting, and before/after snapshot
checks. There is no crash-resume or production promotion; an interrupted run
must not be treated as successful. The mutable-checkout regression run had
455 passes, 5 skips and 89 deselections. The frozen-copy targeted run had
93 passes and 3 deselections, with the snapshot unchanged before and after.
These unit results do not establish an Arena optimization result.

The [first actual Physlib Arena pilot](papers/completion/lean_refactor_arena/evidence/solver-specialization-pilot-2026-09-24/README.md)
finished with `NO_IMPROVEMENT`: 1,372 → 1,365 tokens, but about 0.2873% higher
raw heartbeats in repeated fresh checks of both branch orders. All eight
screening observations verified; the cost gate retained the original and did
not run confirmation. Discovery plus screening used 28 native processes, with
no models or builds. The audit was consistent and the source snapshot unchanged.
The bounded frontier matched minimization: earlier shorter variants filled its
four-state capacity, preventing retention of a longer compiler suggestion.
That untested replacement's cost remains unknown. The archive records this
limitation and the neutral/regressing results, not a new Arena score gain.
Post-archive targeted regression: 456 passed, 5 skipped and 89 deselected,
including a historical bookkeeping test that the smaller/slower draft was not
promoted. Exact commands and native evidence are in the pilot archive above.

## Opt-in balanced frontier comparison

`balanced-frontier-v1` addresses that observed slot bottleneck without raising
resource limits or changing proof admission. At each node it tries the first
support deletion, then the bounded compiler-query sites, then the remaining
support deletions. An independently verified suggestion immediately expands its
child before returning to sibling candidates; an expanded-ID set prevents the
same child being expanded again through the FIFO. Depth, call, proposal, source
byte and retained-state caps apply even to this preferred branch. Root and all
retained nodes count against the same four-state pilot cap. No eviction, hidden
extra slots, parallel Lean process, or unbounded fairness is claimed.

The default modes and offline three-arm demo keep their previous order and
shortest-only nomination. A separate **two-arm** frozen profile compares the
old `frontier-v1` against `balanced-frontier-v1`:

```bash
python -m jevops.arena_solver_pilot --comparison balanced-v1 \
  --problem Electromagnetism.ElectromagneticPotential.time_deriv_time_deriv_electricField_of_isExtrema
```

This command is plan-only. Both arms get eight discovery calls, four states,
depth two, two sites and one draft. Both use `discovery-dual-first-v1`: among
smaller eligible nodes, first nominate those with lower single-pin discovery
raw cost than the seed, ordered by tokens then cost; if there are none, nominate
the shortest tradeoff. This prevents an obviously slower but slightly shorter
draft from excluding a promising draft merely at the nomination cap. These
observations are a heuristic, **not** confirmation or evidence of an all-pin
improvement. The incumbent remains unchanged. Fresh screening uses two repeats
in both orders and confirmation uses three, with the existing 100-raw-unit
noise floor and `strict-dual-v1` gate.

For one pin and an original seed the reservation is **41**: one control + 16
discovery + up to 12 screening + 12 confirmation processes. The arm capacities
are not pooled or expanded after results. The new profile's nomination rule is
shared by both arms, so its comparison isolates scheduling; it is not a pure
replication of the previous three-arm profile's shortest-only nominations.
The same snapshot, preparation lock, capped volume and explicit native opt-in
requirements above apply. Past receipts are not reused as fresh measurements.

Offline fixtures reproduce the four-slot starvation case and exercise failed
hint replay, recursion deduplication, zero/exact resource boundaries, frozen
profiles and fresh selection. They also expose a regression at a four-call
budget: hint probes leave fewer checked states than support-first expansion.
This is a bounded portfolio tradeoff, not a claim of uniformly better search.
The public task is already exposed and cannot establish held-out performance.

The [matched native pilot](papers/completion/lean_refactor_arena/evidence/solver-balanced-pilot-2026-09-24/README.md)
used 25 native processes and finished `NO_IMPROVEMENT`. Balanced admission
reached a verified 1377-token intermediate at 25104564 raw heartbeats, versus
1372 tokens / 27475681 raw for the original (8.6299% lower discovery heartbeats,
five more tokens). Its attempted empty-support child failed whole-proof replay;
the two edits did not compose despite verifying separately. Both arms therefore
nominated the same shorter/slower deletion draft, rejected by fresh strict-dual
screening. The archive retains the unpromoted intermediate, failed composition,
all receipts, unchanged snapshot binding, and consistent bookkeeping audit.
No fresh confirmation of the longer intermediate or official score is claimed.
Post-archive targeted tests: 483 passed, 5 skipped, 89 deselected. The frozen
pre-run suite had 481 passes; the two subsequent tests cover failed composition
and archived accounting. Commands, the corrected preparation record and logs
are in the linked archive.
