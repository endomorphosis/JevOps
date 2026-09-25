# Bounded local tactic portfolio

The opt-in `portfolio-v1` strategy extends `propose_local_batch` in
`jevops/arena_providers.py`. It uses the existing captured closing spans, scoped
premise inventory, structural local-term proposer, project replay and Arena
verification pipeline. It adds no runtime dependency, model, daemon, prover
trust flag or parallel agent framework. `baseline-v1` remains the default.

## Why this increment

The local `ipfs_datasets_py` review at commit
`7f0d38572f92f5fc0cba7a5ddd4bef28523876f3` identified useful proposal-side
patterns in `logic/hammers/reconstructors/lean.py`, `logic/tactician/planner.py`
and `logic/software_verification/tactician/candidate_synthesis.py`: small
tactic portfolios, guarded closure, explicit candidate families and bounded
attempts. Those components are not a general Lean proof-trace reconstructor.
Their solver success flags, source normalization/cache policy and weaker axiom
acceptance are not imported. This increment independently implements the small
portfolio pattern using JevOps' existing interfaces.

The previous proposer iterated methods before premises. With two slots and four
retrieved declarations it could spend both slots on bare `exact` and never try
application. Even bare `apply` leaves premise goals that need arguments. The
new strategy proposes these separate families:

| Family | One candidate | Applicability established by |
| --- | --- | --- |
| `apply_assumption` | `solve \| apply _root_.Library.lemma <;> assumption` | Native Lean inference/application and complete goal closure |
| `exact` | `exact _root_.Library.lemma` | Native elaboration and kernel/type/axiom checks |
| `local_term` | Existing `scoped_proposals.local_terms` output | Native replay; structural matching is only a proposal heuristic |
| `close` | `assumption`, `rfl`, `trivial`, or `solve \| simp_all` | Independent native replay for each tactic |

Library names retain the existing target/alias/dependent/held-out exclusions and
root qualification. Argument-aware application happens **in Lean**, not by
asserting that similar type text is unifiable. `assumption` must close every
premise produced by `apply`; `solve` rejects remaining goals. There is no
unbounded `first` script retaining every search attempt inside the final proof.
No `sorry`, additional axioms, proof-valued feedback from the after-state, or
unchecked generated Python enters this interface.

This is a deterministic heuristic, not trained dynamics, calibrated scoring or
a bandit-performance result. The local-term family still has exact structural
matching limitations; it is not native definitional equality or typeclass search.
External arguments not available from local hypotheses may still be missed.

## Scheduling, bounds and authority

Events keep the established small-span-first ordering. A finite queue visits
each `(event, family)` pair, rotating the starting family by event position,
then consumes one more template from each pair on subsequent passes. Empty
families do not consume draft slots. Duplicate or non-shortening edits consume
template work but not draft slots. This mitigates method-major starvation; a
small finite cap **does not guarantee** visiting every family or every goal.

Limits are explicit and identity-bound: up to 64 events, 4,096 query nodes per
event, eight retrieved premises and eight emitted drafts. `max_templates`
defaults to 128 and accepts 0–512. Zero is exhaustion, never a default. One
lazy local-term search per visited event is bounded by two applications, 64
terms and 2,048 checks. Reports retain attempted template counts, accepted
draft counts by family, per-event search diagnostics and truncation. Retained
rankings share the existing 1 MiB byte ceiling. Full capture validation and
bounded per-event inventory/exclusion scans remain setup work; the template
counter does not pretend to measure them or native Lean heartbeats.

`NO_CONSTANTS` skips library retrieval but can still use typed locals and core
closing tactics. A premise scan overflow cannot supply a partial library
ranking; nonlibrary families remain possible. Query overflow abstains on that
event. Unsupported wrappers and synthetic branch headers are still excluded.

The request hash binds the strategy, schedule, templates, local search bounds,
source, trace, exporter, index, scope and environment. It is an identity, not a
proof. Draft reports retain `proof_verified=false`, `proof_admitted=false` and
`fresh_verification_required=true`. Native replay regenerates the exact original
project context. Successful local replay is not whole-proof admission: fresh
whole-source checks on every required pin, standard axiom policy, and existing
cost/confirmation gates remain mandatory. This does not alter outer-loop
promotion, training, model endpoints or execution isolation.

## Offline generation

Use source-bound capture, inventory and scope artifacts from the existing
adapter (a project capture result's nested `capture` object is the CLI input):

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m jevops.arena_providers --problem YOUR_PROBLEM \
  --premises /path/to/inventory.json --scope /path/to/scope.json \
  --capture /path/to/capture.json --local-strategy portfolio-v1 \
  --cap 2 --max-templates 128 --output-dir /path/to/new-drafts
```

Add `--corpus` for custom records. Existing output directories are refused.
No native/model call occurs during generation. Nondefault local options without
`--capture` are rejected, rather than silently executing another mode.

## Matched experiment protocol

`tools/run_local_premise_pilot.py --comparison local-portfolio` compares local
`baseline-v1` with `portfolio-v1`. The historical default `whole-local` plan is
unchanged. Both local strategies share a fresh capture and all-pin native
inventory, receive the same draft/replay/screen ceilings, and alternate replay
and screen order. Search generation work differs and is not claimed to be free
or time-matched. Replay failures do not prune independent whole-source screening.
Every screen stops at its first non-verified pin. Only all-pin survivors enter
fresh baseline/candidate heartbeat trials in both execution orders, twice each.

For the three-pin Strata task, two slots per strategy reserve at most **83**
native processes: 11 discovery, 12 screen, 60 measurement. Unused ceiling is
not measured expenditure. This is an exploratory public-warmup task with
reference-informed nominees, not a held-out generalization test. No API costs
or official score are inferred. The runner does not promote a winner.

Plan only (offline):

```bash
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py \
  --nominees papers/completion/lean_refactor_arena/evidence/local-premise-core-nominees.json \
  --comparison local-portfolio --cap 2 --max-processes 83
```

For execution, use the [frozen pilot instructions](ARENA_LOCAL_PREMISE_PILOT.md#reproduction)
with `--comparison local-portfolio --max-processes 83`, a new snapshot/output,
and its actual manifest hash. Retain the existing preparation lock, capped
50 GB volume and installed project bindings. No provisioning is performed by
this runner. Execution is single-process trusted-local, not OS sandboxed or
proof of cross-process store safety. Dependency fingerprinting remains global
work and contributes to wall time.

## Tests and native controls

`tests/test_local_tactic_portfolio.py` covers deterministic interleaving,
legacy ordering, duplicate suppression, zero/exact/invalid bounds, scoped
exclusions, scan overflow and typed local search without constant features.
The existing local protocol tests also exercise forged/stale captures and CLI
activation for both strategies. Pilot tests enforce separate replay ceilings
and continue independent screening after failed replay; transient failures do
not become semantic rejection or measurement eligibility.

The opt-in native controls use only installed Lean and core definitions:

1. A lemma `library_step {p : Prop} (h : p) : p ∨ True` needs an argument.
   At equal two-candidate budgets, baseline has **0/2** accepted candidates;
   portfolio has **1/2**, with `apply` inferring the proposition and `assumption`
   supplying `h`. Both local replay and fresh complete verification must pass.
2. Without `h`, applying that lemma leaves an unsolved premise: rejected.
3. Replacing the library lemma with an extra axiom must be rejected by the
   unchanged transitive axiom audit, even though application closes the goal.

Both negative controls produce 0/2 accepted candidates in each strategy. All
three controls passed separately on **4.26.0 (66.35 s)** and **4.29.1 (66.89 s)**,
30 native launches per version, including capture, original controls and the
four independent local/whole-source candidate checks per case. These examples
are mechanism tests, not benchmark wins or measured heartbeat improvements.

Reproduce one installed version at a time:

```bash
env JEVOPS_ARENA_NATIVE_TESTS=1 JEVOPS_PORTFOLIO_LEAN_TAG=v4.26.0 \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_local_tactic_portfolio.py -k native
```

Set `JEVOPS_PORTFOLIO_LEAN_TAG=v4.29.1` for the second run. Without the explicit
native opt-in these tests skip; no download or API fallback is performed.

The broader offline regression run passed **589 tests**, skipped 18 opt-in
native cases and deselected nine older auto-native cases in **9.93 s**:

```bash
env -u JEVOPS_ARENA_NATIVE_TESTS -u JEVOPS_ARENA_DOCKER_TESTS \
  JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  python -m pytest -q --tb=short --test-seal=off -p no:cacheprovider \
  tests/test_arena_local.py tests/test_local_premise_pilot.py \
  tests/test_local_premise_replay.py tests/test_local_tactic_portfolio.py \
  tests/test_arena_premises.py tests/test_arena_providers.py tests/test_premise_search.py \
  tests/test_arena.py tests/test_arena_trial.py tests/test_arena_pareto.py \
  tests/test_refactor_prompts.py tests/test_refactor_prompt_archives.py tests/test_scoped_proposals.py \
  -k 'not native_generated and not before_context_never_copies and not stale_capture_abstains and not native_admission'
```

This is a focused integration suite, not a claim that the entire dirty checkout
or every Lean version has been tested.

## Frozen Strata result (2026-09-24)

The [retained report](papers/completion/lean_refactor_arena/evidence/local-tactic-portfolio-2026-09-24/report.json)
completed the protocol, but found **no accepted improvement**:

| Strategy | Drafts / first-pin screens | Checked local closures | All-pin-valid |
| --- | ---: | ---: | ---: |
| Local `baseline-v1` | 2 | 0 | 0 |
| Local `portfolio-v1` | 2 | 0 | 0 |

All three original-proof controls passed; all eight library nominees were
available on every pin. Capture again validated all **37** selected observations.
All four replay baselines passed the original-environment kernel and standard
axiom checks. Candidate rejection was not caused by the earlier opaque-have or
module-audit failure. The exact candidate outcomes were:

- Baseline: two bare lemmas at event 15 (`split at Hdef <;> simp_all`), both
  rejected for type mismatch.
- Portfolio: `exact _root_.Core.updatedStatesInit` at event 10 was incompatible
  with the goal `ks'.Nodup`. `assumption` at event 24 could not derive that
  proposition from the available hypotheses. Both failed fresh whole-source
  screening as well, with `candidate_errors` on 4.29.1. The remaining pins were
  not spent on already-rejected candidates.

The portfolio tried **9 templates** (7 not shorter, 2 drafts) versus the old
baseline's **66** (64 not shorter, 2 drafts), but prepared **37 event records /
31 rankings** versus **13 / 9**. It also visited three local-term searches.
Thus template work decreased while retrieval/setup work increased. No separate
generation latency was measured, so this is not evidence of a speedup. The
fixed two-slot cap emitted one `exact` and one `close` draft: **no guarded
application draft** made this real-project screen. Finite budget and
strict-shortening filters remain material limitations, even with rotation.

The run used **15 reservations and native launches**: 3 original controls,
3 inventory probes, 1 capture, 4 replays and 4 screens. Reported wall time was
**404.9912 seconds**, including global dependency identity work. There were no
all-pin-valid survivors, so no heartbeat measurement or confirmation ran.
Shorter unverified source strings (224 reference tokens versus 221–223 draft
tokens) are **not** credited compression. No score, superiority, dollar savings
or training improvement was established. API/electricity cost remains unmeasured;
there were zero model calls, builds, downloads and promotions.

Evidence retains the unaltered plan, context, report and before/after source
checks, plus a [compact summary](papers/completion/lean_refactor_arena/evidence/local-tactic-portfolio-2026-09-24/summary.json)
with drafts, origins, replay diagnostics, work counts, full raw artifact paths
and SHA-256 content hashes. Both source checks are `UNCHANGED`. These hashes
identify records; they are not new verification events or proof certificates.

The executed plan ID is
`932ece465cd1788440f3e72daa1cfb7d12ff64cdf6179dd665cf3aa9151c32dd`,
with frozen source manifest
`142d4d9739fbeb67750c2b2c68adbf3c0fc99ca0f74daa250eab0586e6f42495`.
The retained run root is
`/home/barberb/.local/state/jevops-arena-provision-Nr5jXM/work/local-tactic-portfolio-20260924-fQILB1`.
The exact executed arguments were:

```bash
ARENA_PREP=/home/barberb/.local/state/jevops-arena-provision-Nr5jXM
ARENA_RUN="$ARENA_PREP/work/local-tactic-portfolio-20260924-fQILB1"
ARENA_SNAPSHOT="$ARENA_RUN/snapshot"
env JEVOPS_REGISTER_LRA_HOOKS=0 JEVOPS_USE_EXTERNAL_DEPS=0 JEVOPS_USE_EXTERNAL_ROUTER=0 \
  TMPDIR="$ARENA_PREP/work/tmp" JEVOPS_CAS_DIR="$ARENA_RUN/cas" \
  python -I -B "$ARENA_SNAPSHOT/papers/completion/lean_refactor_arena/tools/run_local_premise_pilot.py" \
  --execute --comparison local-portfolio --cap 2 --max-processes 83 \
  --nominees "$ARENA_SNAPSHOT/inputs/nominees.json" \
  --projects "$ARENA_SNAPSHOT/inputs/projects.json" \
  --preparation-root "$ARENA_PREP" --elan-home "$ARENA_PREP/work/elan" \
  --snapshot-manifest-sha256 142d4d9739fbeb67750c2b2c68adbf3c0fc99ca0f74daa250eab0586e6f42495 \
  --output "$ARENA_RUN/run"
```

That output now exists and is intentionally protected from overwrite; a repeat
needs a new output inside the capped volume. A changed implementation also
requires a new source snapshot and its actual hash.

The next hypothesis to test is **goal-directed applicability and span choice**:
most cheap closing spans are already too short for a multi-step application to
improve, and the union of local-type constant features retrieves lemmas whose
conclusions do not match the goal. A follow-up should isolate goal-conclusion
retrieval from span scheduling under the same native budget. It must not label
this negative pilot as a win, adapt a frozen run midstream, weaken admission,
or automatically train on failed candidates. General ATP reconstruction,
learned tactic selection and model-assisted argument generation remain deferred.
